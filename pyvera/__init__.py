"""Vera Controller Python API.

This lib is designed to simplify communication with Vera controllers
"""
from abc import ABC, abstractmethod
import collections
from datetime import datetime
import json
import logging
import os
import shlex
import threading
import time
from typing import Any, Callable, DefaultDict, Dict, List, Optional, Tuple, Union, cast

import requests

TIMESTAMP_NONE = {"dataversion": 1, "loadtime": 0}

# Time to block on Vera poll if there are no changes in seconds
SUBSCRIPTION_WAIT = 30
# Min time to wait for event in miliseconds
SUBSCRIPTION_MIN_WAIT = 200
# Timeout for requests calls, as vera sometimes just sits on sockets.
TIMEOUT = SUBSCRIPTION_WAIT
# VeraLock set target timeout in seconds
LOCK_TARGET_TIMEOUT_SEC = 30

CATEGORY_DIMMER = 2
CATEGORY_SWITCH = 3
CATEGORY_ARMABLE = 4
CATEGORY_THERMOSTAT = 5
CATEGORY_LOCK = 7
CATEGORY_CURTAIN = 8
CATEGORY_REMOTE = 9
CATEGORY_GENERIC = 11
CATEGORY_SENSOR = 12
CATEGORY_SCENE_CONTROLLER = 14
CATEGORY_HUMIDITY_SENSOR = 16
CATEGORY_TEMPERATURE_SENSOR = 17
CATEGORY_LIGHT_SENSOR = 18
CATEGORY_POWER_METER = 21
CATEGORY_VERA_SIREN = 24
CATEGORY_UV_SENSOR = 28
CATEGORY_GARAGE_DOOR = 32


# How long to wait before retrying Vera
SUBSCRIPTION_RETRY = 9

# Vera state codes see http://wiki.micasaverde.com/index.php/Luup_Requests
STATE_NO_JOB = -1
STATE_JOB_WAITING_TO_START = 0
STATE_JOB_IN_PROGRESS = 1
STATE_JOB_ERROR = 2
STATE_JOB_ABORTED = 3
STATE_JOB_DONE = 4
STATE_JOB_WAITING_FOR_CALLBACK = 5
STATE_JOB_REQUEUE = 6
STATE_JOB_PENDING_DATA = 7

STATE_NOT_PRESENT = 999

ChangedDevicesValue = Tuple[List[dict], dict]
LockCode = Tuple[str, str, str]
UserCode = Tuple[str, str]
SubscriptionCallback = Callable[["VeraDevice"], None]


def init_logging(logger: Any, logger_level: Optional[str]) -> None:
    """Initialize the logger."""
    # Set logging level (such as INFO, DEBUG, etc) via an environment variable
    # Defaults to WARNING log level unless PYVERA_LOGLEVEL variable exists
    if logger_level:
        logger.setLevel(logger_level)
        log_handler = logging.StreamHandler()
        log_handler.setFormatter(
            logging.Formatter("%(levelname)s@{%(name)s:%(lineno)d} - %(message)s")
        )
        logger.addHandler(log_handler)


# Set up the console logger for debugging
LOG = logging.getLogger(__name__)
init_logging(LOG, os.environ.get("PYVERA_LOGLEVEL"))
LOG.debug("DEBUG logging is ON")


# pylint: disable=too-many-instance-attributes
class VeraController:
    """Class to interact with the Vera device."""

    temperature_units = "C"

    def __init__(
        self,
        base_url: str,
        subscription_registry: Optional["AbstractSubscriptionRegistry"] = None,
    ):
        """Init Vera controller at the given URL.

        base_url: Vera API URL, eg http://vera:3480.
        """

        self.base_url = base_url
        self.devices: List[VeraDevice] = []
        self.scenes: List[VeraScene] = []
        self.temperature_units = "C"
        self.version = None
        self.model = None
        self.serial_number = None
        self.device_services_map: Dict[int, List[dict]] = {}
        self.subscription_registry = subscription_registry or SubscriptionRegistry()
        self.subscription_registry.set_controller(self)
        self.categories: Dict[int, str] = {}
        self.device_id_map: Dict[int, VeraDevice] = {}

    def data_request(self, payload: dict, timeout: int = TIMEOUT) -> requests.Response:
        """Perform a data_request and return the result."""
        request_url = self.base_url + "/data_request"
        response = requests.get(request_url, timeout=timeout, params=payload)
        response.encoding = response.encoding if response.encoding else "utf-8"
        return response

    def get_simple_devices_info(self) -> None:
        """Get basic device info from Vera."""
        j = self.data_request({"id": "sdata"}).json()

        self.scenes = []
        items = j.get("scenes")

        for item in items:
            self.scenes.append(VeraScene(item, self))

        if j.get("temperature"):
            self.temperature_units = j.get("temperature")

        self.categories = {}
        cats = j.get("categories")

        for cat in cats:
            self.categories[cat.get("id")] = cat.get("name")

        self.device_id_map = {}

        devs = j.get("devices")
        for dev in devs:
            dev["categoryName"] = self.categories.get(dev.get("category"))
            self.device_id_map[dev.get("id")] = dev

    def get_scenes(self) -> List["VeraScene"]:
        """Get list of scenes."""

        self.get_simple_devices_info()

        return self.scenes

    def get_device_by_name(self, device_name: str) -> Optional["VeraDevice"]:
        """Search the list of connected devices by name.

        device_name param is the string name of the device
        """

        # Find the device for the vera device name we are interested in
        found_device = None
        for device in self.get_devices():
            if device.name == device_name:
                found_device = device
                # found the first (and should be only) one so we will finish
                break

        if found_device is None:
            LOG.debug("Did not find device with %s", device_name)

        return found_device

    def get_device_by_id(self, device_id: int) -> Optional["VeraDevice"]:
        """Search the list of connected devices by ID.

        device_id param is the integer ID of the device
        """

        # Find the device for the vera device name we are interested in
        found_device = None
        for device in self.get_devices():
            if device.device_id == device_id:
                found_device = device
                # found the first (and should be only) one so we will finish
                break

        if found_device is None:
            LOG.debug("Did not find device with %s", device_id)

        return found_device

    def get_devices(self, category_filter: str = "") -> List["VeraDevice"]:
        """Get list of connected devices.

        category_filter param is an array of strings.  If specified, this
        function will only return devices with category names which match the
        strings in this filter.
        """

        # the Vera rest API is a bit rough so we need to make 2 calls to get
        # all the info we need
        self.get_simple_devices_info()

        json_data = self.data_request({"id": "status", "output_format": "json"}).json()

        self.devices = []
        items = json_data.get("devices")
        alerts = json_data.get("alerts", ())

        for item in items:
            item["deviceInfo"] = self.device_id_map.get(item.get("id")) or {}
            item_alerts = [
                alert for alert in alerts if alert.get("PK_Device") == item.get("id")
            ]
            device_category = item.get("deviceInfo", {}).get("category")

            device: VeraDevice
            if device_category == CATEGORY_DIMMER:
                device = VeraDimmer(item, item_alerts, self)
            elif device_category in (CATEGORY_SWITCH, CATEGORY_VERA_SIREN):
                device = VeraSwitch(item, item_alerts, self)
            elif device_category == CATEGORY_THERMOSTAT:
                device = VeraThermostat(item, item_alerts, self)
            elif device_category == CATEGORY_LOCK:
                device = VeraLock(item, item_alerts, self)
            elif device_category == CATEGORY_CURTAIN:
                device = VeraCurtain(item, item_alerts, self)
            elif device_category == CATEGORY_ARMABLE:
                device = VeraBinarySensor(item, item_alerts, self)
            elif device_category in (
                CATEGORY_SENSOR,
                CATEGORY_HUMIDITY_SENSOR,
                CATEGORY_TEMPERATURE_SENSOR,
                CATEGORY_LIGHT_SENSOR,
                CATEGORY_POWER_METER,
                CATEGORY_UV_SENSOR,
            ):
                device = VeraSensor(item, item_alerts, self)
            elif device_category in (CATEGORY_SCENE_CONTROLLER, CATEGORY_REMOTE):
                device = VeraSceneController(item, item_alerts, self)
            elif device_category == CATEGORY_GARAGE_DOOR:
                device = VeraGarageDoor(item, item_alerts, self)
            else:
                device = VeraDevice(item, item_alerts, self)

            self.devices.append(device)

            if device.is_armable and device_category not in (
                CATEGORY_SWITCH,
                CATEGORY_VERA_SIREN,
                CATEGORY_CURTAIN,
                CATEGORY_GARAGE_DOOR,
            ):
                self.devices.append(VeraArmableDevice(item, item_alerts, self))

        return [
            device
            for device in self.devices
            if not category_filter
            or (
                device.category_name is not None
                and device.category_name != ""
                and device.category_name in category_filter
            )
        ]

    def refresh_data(self) -> Dict[int, "VeraDevice"]:
        """Refresh mapping from device ids to devices."""
        # Note: This function is side-effect free and appears to be unused.
        # Safe to erase?

        # the Vera rest API is a bit rough so we need to make 2 calls
        # to get all the info e need
        j = self.data_request({"id": "sdata"}).json()

        self.temperature_units = j.get("temperature", "C")
        self.model = j.get("model")
        self.version = j.get("version")
        self.serial_number = j.get("serial_number")

        categories = {}
        cats = j.get("categories")

        for cat in cats:
            categories[cat.get("id")] = cat.get("name")

        device_id_map = {}

        devs = j.get("devices")
        for dev in devs:
            dev["categoryName"] = categories.get(dev.get("category"))
            device_id_map[dev.get("id")] = dev

        return device_id_map

    def map_services(self) -> None:
        """Get full Vera device service info."""
        # Note: This function updates the device_services_map, but that map does
        # not appear to be used.  Safe to erase?
        self.get_simple_devices_info()

        j = self.data_request({"id": "status", "output_format": "json"}).json()

        service_map = {}

        items = j.get("devices")

        for item in items:
            service_map[item.get("id")] = item.get("states")

        self.device_services_map = service_map

    def get_changed_devices(self, timestamp: dict) -> ChangedDevicesValue:
        """Get data since last timestamp.

        This function blocks until a change is returned by the Vera, or the
        request times out.

        timestamp param: the timestamp returned by the last invocation of this
        function.  Use a timestamp of TIMESTAMP_NONE for the first invocation.
        """
        payload = {
            "timeout": SUBSCRIPTION_WAIT,
            "minimumdelay": SUBSCRIPTION_MIN_WAIT,
            "id": "lu_sdata",
        }
        payload.update(timestamp)

        # double the timeout here so requests doesn't timeout before vera
        LOG.debug("get_changed_devices() requesting payload %s", str(payload))
        response = self.data_request(payload, TIMEOUT * 2)
        response.raise_for_status()

        # If the Vera disconnects before writing a full response (as lu_sdata
        # will do when interrupted by a Luup reload), the requests module will
        # happily return 200 with an empty string. So, test for empty response,
        # so we don't rely on the JSON parser to throw an exception.
        if response.text == "":
            raise PyveraError("Empty response from Vera")

        # Catch a wide swath of what the JSON parser might throw, within
        # reason. Unfortunately, some parsers don't specifically return
        # json.decode.JSONDecodeError, but so far most seem to derive what
        # they do throw from ValueError, so that's helpful.
        try:
            result = response.json()
        except ValueError as ex:
            raise PyveraError("JSON decode error: " + str(ex))

        if not (
            isinstance(result, dict)
            and "loadtime" in result
            and "dataversion" in result
        ):
            raise PyveraError("Unexpected/garbled response from Vera")

        # At this point, all good. Update timestamp and return change data.
        device_data = result.get("devices", [])
        timestamp = {
            "loadtime": result.get("loadtime", 0),
            "dataversion": result.get("dataversion", 1),
        }
        return device_data, timestamp

    def get_alerts(self, timestamp: dict) -> List[dict]:
        """Get alerts that have triggered since last timestamp.

        Note that unlike get_changed_devices, this is non-blocking.

        timestamp param: the timestamp returned by the prior (not current)
        invocation of get_changed_devices.  Use a timestamp of TIMESTAMP_NONE
        for the first invocation.
        """

        payload = {
            "LoadTime": timestamp["loadtime"],
            "DataVersion": timestamp["dataversion"],
            "id": "status",
        }

        LOG.debug("get_alerts() requesting payload %s", str(payload))
        response = self.data_request(payload)
        response.raise_for_status()

        if response.text == "":
            raise PyveraError("Empty response from Vera")

        try:
            result = response.json()
        except ValueError as ex:
            raise PyveraError("JSON decode error: " + str(ex))

        if not (
            isinstance(result, dict)
            and "LoadTime" in result
            and "DataVersion" in result
        ):
            raise PyveraError("Unexpected/garbled response from Vera")

        return result.get("alerts", [])

    # The subscription thread (if you use it) runs in the background and blocks
    # waiting for state changes (a.k.a. events) from the Vera controller.  When
    # an event occurs, the subscription thread will invoke any callbacks for
    # affected devices.
    #
    # The subscription thread is (obviously) run on a separate thread.  This
    # means there is a potential for race conditions.  Pyvera contains no locks
    # or synchronization primitives.  To avoid race conditions, clients should
    # do the following:
    #
    # (a) set up Pyvera, including registering any callbacks, before starting
    # the subscription thread.
    #
    # (b) Once the subscription thread has started, realize that callbacks will
    # be invoked in the context of the subscription thread.  Only access Pyvera
    # from those callbacks from that point forwards.

    def start(self) -> None:
        """Start the subscription thread."""
        self.subscription_registry.start()

    def stop(self) -> None:
        """Stop the subscription thread."""
        self.subscription_registry.stop()

    def register(self, device: "VeraDevice", callback: SubscriptionCallback) -> None:
        """Register a device and callback with the subscription service.

        The callback will be called from the subscription thread when the device
        is updated.
        """
        self.subscription_registry.register(device, callback)

    def unregister(self, device: "VeraDevice", callback: SubscriptionCallback) -> None:
        """Unregister a device and callback with the subscription service."""
        self.subscription_registry.unregister(device, callback)


# pylint: disable=too-many-public-methods
class VeraDevice:
    """Class to represent each vera device."""

    def __init__(
        self, json_obj: dict, json_alerts: List[dict], vera_controller: VeraController
    ):
        """Init object."""
        self.json_state = json_obj
        self.device_id = self.json_state.get("id")
        self.vera_controller = vera_controller
        self.name = ""
        self.alerts: List[VeraAlert] = []
        self.set_alerts(json_alerts)

        if self.json_state.get("deviceInfo"):
            device_info = self.json_state.get("deviceInfo", {})
            self.category = device_info.get("category")
            self.category_name = device_info.get("categoryName")
            self.name = device_info.get("name")
        else:
            self.category_name = ""

        if not self.name:
            if self.category_name:
                self.name = "Vera " + self.category_name + " " + str(self.device_id)
            else:
                self.name = "Vera Device " + str(self.device_id)

    def __repr__(self) -> str:
        """Get a string representation."""
        return f"{self.__class__.__name__} (id={self.device_id} category={self.category_name} name={self.name})"

    @property
    def switch_service(self) -> str:
        """Vera service string for switch."""
        return "urn:upnp-org:serviceId:SwitchPower1"

    @property
    def dimmer_service(self) -> str:
        """Vera service string for dimmer."""
        return "urn:upnp-org:serviceId:Dimming1"

    @property
    def security_sensor_service(self) -> str:
        """Vera service string for armable sensors."""
        return "urn:micasaverde-com:serviceId:SecuritySensor1"

    @property
    def window_covering_service(self) -> str:
        """Vera service string for window covering service."""
        return "urn:upnp-org:serviceId:WindowCovering1"

    @property
    def lock_service(self) -> str:
        """Vera service string for lock service."""
        return "urn:micasaverde-com:serviceId:DoorLock1"

    @property
    def thermostat_operating_service(self) -> Tuple[str]:
        """Vera service string HVAC operating mode."""
        return ("urn:upnp-org:serviceId:HVAC_UserOperatingMode1",)

    @property
    def thermostat_fan_service(self) -> str:
        """Vera service string HVAC fan operating mode."""
        return "urn:upnp-org:serviceId:HVAC_FanOperatingMode1"

    @property
    def thermostat_cool_setpoint(self) -> str:
        """Vera service string Temperature Setpoint1 Cool."""
        return "urn:upnp-org:serviceId:TemperatureSetpoint1_Cool"

    @property
    def thermostat_heat_setpoint(self) -> str:
        """Vera service string Temperature Setpoint Heat."""
        return "urn:upnp-org:serviceId:TemperatureSetpoint1_Heat"

    @property
    def thermostat_setpoint(self) -> str:
        """Vera service string Temperature Setpoint."""
        return "urn:upnp-org:serviceId:TemperatureSetpoint1"

    @property
    def color_service(self) -> str:
        """Vera service string for color."""
        return "urn:micasaverde-com:serviceId:Color1"

    def vera_request(self, **kwargs: Any) -> requests.Response:
        """Perfom a vera_request for this device."""
        request_payload = {"output_format": "json", "DeviceNum": self.device_id}
        request_payload.update(kwargs)

        return self.vera_controller.data_request(request_payload)

    def set_service_value(
        self,
        service_id: Union[str, Tuple[str, ...]],
        set_name: str,
        parameter_name: str,
        value: Any,
    ) -> None:
        """Set a variable on the vera device.

        This will call the Vera api to change device state.
        """
        payload = {
            "id": "lu_action",
            "action": "Set" + set_name,
            "serviceId": service_id,
            parameter_name: value,
        }
        result = self.vera_request(**payload)
        LOG.debug(
            "set_service_value: " "result of vera_request with payload %s: %s",
            payload,
            result.text,
        )

    def call_service(self, service_id: str, action: str) -> requests.Response:
        """Call a Vera service.

        This will call the Vera api to change device state.
        """
        result = self.vera_request(id="action", serviceId=service_id, action=action)
        LOG.debug(
            "call_service: " "result of vera_request with id %s: %s",
            service_id,
            result.text,
        )
        return result

    def set_cache_value(self, name: str, value: Any) -> None:
        """Set a variable in the local state dictionary.

        This does not change the physical device. Useful if you want the
        device state to refect a new value which has not yet updated from
        Vera.
        """
        dev_info = self.json_state.get("deviceInfo", {})
        if dev_info.get(name.lower()) is None:
            LOG.error("Could not set %s for %s (key does not exist).", name, self.name)
            LOG.error("- dictionary %s", dev_info)
            return
        dev_info[name.lower()] = str(value)

    def set_cache_complex_value(self, name: str, value: Any) -> None:
        """Set a variable in the local complex state dictionary.

        This does not change the physical device. Useful if you want the
        device state to refect a new value which has not yet updated from
        Vera.
        """
        for item in self.json_state.get("states", []):
            if item.get("variable") == name:
                item["value"] = str(value)

    def get_complex_value(self, name: str) -> Any:
        """Get a value from the service dictionaries.

        It's best to use get_value if it has the data you require since
        the vera subscription only updates data in dev_info.
        """
        for item in self.json_state.get("states", []):
            if item.get("variable") == name:
                return item.get("value")
        return None

    def get_all_values(self) -> dict:
        """Get all values from the deviceInfo area.

        The deviceInfo data is updated by the subscription service.
        """
        return cast(dict, self.json_state.get("deviceInfo"))

    def get_value(self, name: str) -> Any:
        """Get a value from the dev_info area.

        This is the common Vera data and is the best place to get state from
        if it has the data you require.

        This data is updated by the subscription service.
        """
        return self.get_strict_value(name.lower())

    def get_strict_value(self, name: str) -> Any:
        """Get a case-sensitive keys value from the dev_info area."""
        dev_info = self.json_state.get("deviceInfo", {})
        return dev_info.get(name, None)

    def refresh_complex_value(self, name: str) -> Any:
        """Refresh a value from the service dictionaries.

        It's best to use get_value / refresh if it has the data you need.
        """
        for item in self.json_state.get("states", []):
            if item.get("variable") == name:
                service_id = item.get("service")
                result = self.vera_request(
                    **{
                        "id": "variableget",
                        "output_format": "json",
                        "DeviceNum": self.device_id,
                        "serviceId": service_id,
                        "Variable": name,
                    }
                )
                item["value"] = result.text
                return item.get("value")
        return None

    def set_alerts(self, json_alerts: List[dict]) -> None:
        """Convert JSON alert data to VeraAlerts."""
        self.alerts = [VeraAlert(json_alert, self) for json_alert in json_alerts]

    def get_alerts(self) -> List["VeraAlert"]:
        """Get any alerts present during the most recent poll cycle."""
        return self.alerts

    def refresh(self) -> None:
        """Refresh the dev_info data used by get_value.

        Only needed if you're not using subscriptions.
        """
        j = self.vera_request(id="sdata", output_format="json").json()
        devices = j.get("devices")
        for device_data in devices:
            if device_data.get("id") == self.device_id:
                self.update(device_data)

    def update(self, params: dict) -> None:
        """Update the dev_info data from a dictionary.

        Only updates if it already exists in the device.
        """
        dev_info = self.json_state.get("deviceInfo", {})
        dev_info.update({k: params[k] for k in params if dev_info.get(k)})

    @property
    def is_armable(self) -> bool:
        """Device is armable."""
        return self.get_value("Armed") is not None

    @property
    def is_armed(self) -> bool:
        """Device is armed now."""
        return cast(str, self.get_value("Armed")) == "1"

    @property
    def is_dimmable(self) -> bool:
        """Device is dimmable."""
        return cast(int, self.category) == CATEGORY_DIMMER

    @property
    def is_trippable(self) -> bool:
        """Device is trippable."""
        return self.get_value("Tripped") is not None

    @property
    def is_tripped(self) -> bool:
        """Device is tripped now."""
        return cast(str, self.get_value("Tripped")) == "1"

    @property
    def has_battery(self) -> bool:
        """Device has a battery."""
        return self.get_value("BatteryLevel") is not None

    @property
    def battery_level(self) -> int:
        """Battery level as a percentage."""
        return cast(int, self.get_value("BatteryLevel"))

    @property
    def last_trip(self) -> str:
        """Time device last tripped."""
        # Vera seems not to update this for my device!
        return cast(str, self.get_value("LastTrip"))

    @property
    def light(self) -> int:
        """Light level in lux."""
        return cast(int, self.get_value("Light"))

    @property
    def level(self) -> int:
        """Get level from vera."""
        # Used for dimmers, curtains
        # Have seen formats of 10, 0.0 and "0%"!
        level = self.get_value("level")
        try:
            return int(float(level))
        except (TypeError, ValueError):
            pass
        try:
            return int(level.strip("%"))
        except (TypeError, AttributeError, ValueError):
            pass
        return 0

    @property
    def temperature(self) -> float:
        """Get the temperature.

        You can get units from the controller.
        """
        return cast(float, self.get_value("Temperature"))

    @property
    def humidity(self) -> float:
        """Get the humidity level in percent."""
        return cast(float, self.get_value("Humidity"))

    @property
    def power(self) -> int:
        """Get the current power useage in watts."""
        return cast(int, self.get_value("Watts"))

    @property
    def energy(self) -> int:
        """Get the energy usage in kwh."""
        return cast(int, self.get_value("kwh"))

    @property
    def room_id(self) -> int:
        """Get the Vera Room ID."""
        return cast(int, self.get_value("room"))

    @property
    def comm_failure(self) -> bool:
        """Return the Communication Failure Flag."""
        return cast(str, self.get_strict_value("commFailure")) != "0"

    @property
    def vera_device_id(self) -> int:
        """Get the ID Vera uses to refer to the device."""
        return cast(int, self.device_id)

    @property
    def should_poll(self) -> bool:
        """Whether polling is needed if using subscriptions for this device."""
        return False


class VeraSwitch(VeraDevice):
    """Class to add switch functionality."""

    def set_switch_state(self, state: int) -> None:
        """Set the switch state, also update local state."""
        self.set_service_value(self.switch_service, "Target", "newTargetValue", state)
        self.set_cache_value("Status", state)

    def switch_on(self) -> None:
        """Turn the switch on, also update local state."""
        self.set_switch_state(1)

    def switch_off(self) -> None:
        """Turn the switch off, also update local state."""
        self.set_switch_state(0)

    def is_switched_on(self, refresh: bool = False) -> bool:
        """Get switch state.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        Refresh is only needed if you're not using subscriptions.
        """
        if refresh:
            self.refresh()
        val = self.get_value("Status")
        return cast(str, val) == "1"


class VeraDimmer(VeraSwitch):
    """Class to add dimmer functionality."""

    def get_brightness(self, refresh: bool = False) -> int:
        """Get dimmer brightness.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        Refresh is only needed if you're not using subscriptions.
        Converts the Vera level property for dimmable lights from a percentage
        to the 0 - 255 scale used by HA.
        """
        if refresh:
            self.refresh()
        brightness = 0
        percent = self.level
        if percent > 0:
            brightness = round(percent * 2.55)
        return int(brightness)

    def set_brightness(self, brightness: int) -> None:
        """Set dimmer brightness.

        Converts the Vera level property for dimmable lights from a percentage
        to the 0 - 255 scale used by HA.
        """
        percent = 0
        if brightness > 0:
            percent = round(brightness / 2.55)

        self.set_service_value(
            self.dimmer_service, "LoadLevelTarget", "newLoadlevelTarget", percent
        )
        self.set_cache_value("level", percent)

    def get_color_index(
        self, colors: List[str], refresh: bool = False
    ) -> Optional[List[int]]:
        """Get color index.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        """
        if refresh:
            self.refresh_complex_value("SupportedColors")

        sup = self.get_complex_value("SupportedColors")
        if sup is None:
            return None

        sup = sup.split(",")
        if not set(colors).issubset(sup):
            return None

        return [sup.index(c) for c in colors]

    def get_color(self, refresh: bool = False) -> Optional[List[int]]:
        """Get color.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        """
        if refresh:
            self.refresh_complex_value("CurrentColor")

        color_index = self.get_color_index(["R", "G", "B"], refresh)
        cur = self.get_complex_value("CurrentColor")
        if color_index is None or cur is None:
            return None

        try:
            val = [cur.split(",")[c] for c in color_index]
            return [int(v.split("=")[1]) for v in val]
        except IndexError:
            return None

    def set_color(self, rgb: List[int]) -> None:
        """Set dimmer color."""

        target = ",".join([str(c) for c in rgb])
        self.set_service_value(
            self.color_service, "ColorRGB", "newColorRGBTarget", target
        )

        rgbi = self.get_color_index(["R", "G", "B"])
        if rgbi is None:
            return

        target = (
            "0=0,1=0,"
            + str(rgbi[0])
            + "="
            + str(rgb[0])
            + ","
            + str(rgbi[1])
            + "="
            + str(rgb[1])
            + ","
            + str(rgbi[2])
            + "="
            + str(rgb[2])
        )
        self.set_cache_complex_value("CurrentColor", target)


class VeraArmableDevice(VeraSwitch):
    """Class to represent a device that can be armed."""

    def set_armed_state(self, state: int) -> None:
        """Set the armed state, also update local state."""
        self.set_service_value(
            self.security_sensor_service, "Armed", "newArmedValue", state
        )
        self.set_cache_value("Armed", state)

    def switch_on(self) -> None:
        """Arm the device."""
        self.set_armed_state(1)

    def switch_off(self) -> None:
        """Disarm the device."""
        self.set_armed_state(0)

    def is_switched_on(self, refresh: bool = False) -> bool:
        """Get armed state.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        Refresh is only needed if you're not using subscriptions.
        """
        if refresh:
            self.refresh()
        val = self.get_value("Armed")
        return cast(str, val) == "1"


class VeraSensor(VeraDevice):
    """Class to represent a supported sensor."""


class VeraBinarySensor(VeraDevice):
    """Class to represent an on / off sensor."""

    def is_switched_on(self, refresh: bool = False) -> bool:
        """Get sensor on off state.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        Refresh is only needed if you're not using subscriptions.
        """
        if refresh:
            self.refresh()
        val = self.get_value("Status")
        return cast(str, val) == "1"


class VeraCurtain(VeraSwitch):
    """Class to add curtains functionality."""

    def open(self) -> None:
        """Open the curtains."""
        self.set_level(100)

    def close(self) -> None:
        """Close the curtains."""
        self.set_level(0)

    def stop(self) -> int:
        """Open the curtains."""
        self.call_service(self.window_covering_service, "Stop")
        return cast(int, self.get_level(True))

    def is_open(self, refresh: bool = False) -> bool:
        """Get curtains state.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        Refresh is only needed if you're not using subscriptions.
        """
        if refresh:
            self.refresh()
        return self.get_level(refresh) > 0

    def get_level(self, refresh: bool = False) -> int:
        """Get open level of the curtains.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        Refresh is only needed if you're not using subscriptions.
        Scale is 0-100
        """
        if refresh:
            self.refresh()
        return self.level

    def set_level(self, level: int) -> None:
        """Set open level of the curtains.

        Scale is 0-100
        """
        self.set_service_value(
            self.dimmer_service, "LoadLevelTarget", "newLoadlevelTarget", level
        )

        self.set_cache_value("level", level)


class VeraLock(VeraDevice):
    """Class to represent a door lock."""

    # target locked (state, time)
    # this is used since sdata does not return proper job status for locks
    lock_target = None

    def set_lock_state(self, state: int) -> None:
        """Set the lock state, also update local state."""
        self.set_service_value(self.lock_service, "Target", "newTargetValue", state)
        self.set_cache_value("locked", state)
        self.lock_target = (str(state), time.time())

    def lock(self) -> None:
        """Lock the door."""
        self.set_lock_state(1)

    def unlock(self) -> None:
        """Unlock the device."""
        self.set_lock_state(0)

    def is_locked(self, refresh: bool = False) -> bool:
        """Get locked state.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        Refresh is only needed if you're not using subscriptions.
        Lock state can also be found with self.get_complex_value('Status')
        """
        if refresh:
            self.refresh()

        # if the lock target matches now
        # or the locking action took too long
        # then reset the target and time
        now = time.time()
        if self.lock_target is not None and (
            self.lock_target[0] == self.get_value("locked")
            or now - self.lock_target[1] >= LOCK_TARGET_TIMEOUT_SEC
        ):
            LOG.debug(
                "Resetting lock target for %s (%s==%s, %s - %s >= %s)",
                self.name,
                self.lock_target[0],
                self.get_value("locked"),
                now,
                self.lock_target[1],
                LOCK_TARGET_TIMEOUT_SEC,
            )
            self.lock_target = None

        locked = cast(str, self.get_value("locked")) == "1"
        if self.lock_target is not None:
            locked = cast(str, self.lock_target[0]) == "1"
            LOG.debug("Lock still in progress for %s: target=%s", self.name, locked)
        return locked

    @staticmethod
    def _parse_usercode(user_code: str) -> Optional[UserCode]:
        # Syntax string: UserID="<pin_slot>" UserName="<pin_code_name>"
        # See http://wiki.micasaverde.com/index.php/Luup_UPnP_Variables_and_Actions#DoorLock1

        try:
            # Get the UserID="" and UserName="" fields separately
            raw_userid, raw_username = shlex.split(user_code)
            # Get the right hand value of UserID=<here>
            userid = raw_userid.split("=")[1]
            # Get the right hand value of UserName=<here>
            username = raw_username.split("=")[1]
        # pylint: disable=broad-except
        except Exception as ex:
            LOG.error("Got unsupported user string %s: %s", user_code, ex)
            return None
        return (userid, username)

    def get_last_user(self, refresh: bool = False) -> Optional[UserCode]:
        """Get the last used PIN user id.

        This is sadly not as useful as it could be.  It will tell you the last
        PIN used -- but if the lock is unlocked, you have no idea if a PIN was
        used or just someone used a key or the knob.  So it is not possible to
        use this API to determine *when* a PIN was used.
        """
        if refresh:
            self.refresh_complex_value("sl_UserCode")
        val = str(self.get_complex_value("sl_UserCode"))

        user = self._parse_usercode(val)
        return user

    def get_last_user_alert(self) -> Optional[UserCode]:
        """Get the PIN used for the action in the last poll cycle.

        Unlike get_last_user(), this function only returns a result when the
        last action taken (such as an unlock) used a PIN.  So this is useful for
        triggering events when a paritcular PIN is used.  Since it relies on the
        poll cycle, this function is a no-op if subscriptions are not used.
        """
        for alert in self.alerts:
            if alert.code == "DL_USERCODE":
                user = self._parse_usercode(alert.value)
                return user
        return None

    def get_low_battery_alert(self) -> int:
        """See if a low battery alert was issued in the last poll cycle."""
        for alert in self.alerts:
            if alert.code == "DL_LOW_BATTERY":
                return 1
        return 0

    # The following three functions are less useful than you might think.  Once
    # a user enters a bad PIN code, get_pin_failed() appears to remain True
    # forever (or at least, until you reboot the Vera?).  Similarly,
    # get_unauth_user(), and get_lock_failed() don't appear to reset.
    # get_last_user() also has this property -- but get_last_user_alert() is
    # more useful.
    #
    # We could implement this as a destructive read -- unset the variables on
    # the Vera after we read them.  But this assumes the Vera only has a single
    # client using this API (otherwise the two clients would interfere with each
    # other).  Also, this technique has an unavoidable race condition -- what if
    # the Vera updates the variable after we've read it but before we clear it?
    #
    # The fundamental problem is with the HTTP API to the Vera.  On the Vera
    # itself you can observe when a variable is written (or overwritten, even
    # with an identical value) by using the Lua function luup.variable_watch().
    # No equivalent appears to exist in the HTTP API.

    def get_pin_failed(self, refresh: bool = False) -> bool:
        """Get if pin failed. True when a bad PIN code was entered."""
        if refresh:
            self.refresh_complex_value("sl_PinFailed")
        return cast(str, self.get_complex_value("sl_PinFailed")) == "1"

    def get_unauth_user(self, refresh: bool = False) -> bool:
        """Get unauth user state. True when a user code entered was outside of a valid date."""
        if refresh:
            self.refresh_complex_value("sl_UnauthUser")
        return cast(str, self.get_complex_value("sl_UnauthUser")) == "1"

    def get_lock_failed(self, refresh: bool = False) -> bool:
        """Get lock failed state. True when the lock fails to operate."""
        if refresh:
            self.refresh_complex_value("sl_LockFailure")
        return cast(str, self.get_complex_value("sl_LockFailure")) == "1"

    def get_pin_codes(self, refresh: bool = False) -> List[LockCode]:
        """Get the list of PIN codes.

        Codes can also be found with self.get_complex_value('PinCodes')
        """
        if refresh:
            self.refresh()
        val = self.get_value("pincodes")

        # val syntax string: <VERSION=3>next_available_user_code_id\tuser_code_id,active,date_added,date_used,PIN_code,name;\t...
        # See (outdated) http://wiki.micasaverde.com/index.php/Luup_UPnP_Variables_and_Actions#DoorLock1

        # Remove the trailing tab
        # ignore the version and next available at the start
        # and split out each set of code attributes
        raw_code_list: List[str] = []
        try:
            raw_code_list = val.rstrip().split("\t")[1:]
        # pylint: disable=broad-except
        except Exception as ex:
            LOG.error("Got unsupported string %s: %s", val, ex)

        # Loop to create a list of codes
        codes = []
        for code in raw_code_list:

            try:
                # Strip off trailing semicolon
                # Create a list from csv
                code_addrs = code.split(";")[0].split(",")

                # Get the code ID (slot) and see if it should have values
                slot, active = code_addrs[:2]
                if active != "0":
                    # Since it has additional attributes, get the remaining ones
                    _, _, pin, name = code_addrs[2:]
                    # And add them as a tuple to the list
                    codes.append((slot, name, pin))
            # pylint: disable=broad-except
            except Exception as ex:
                LOG.error("Problem parsing pin code string %s: %s", code, ex)

        return codes

    @property
    def should_poll(self) -> bool:
        """Determine if we should poll for data."""
        return True


class VeraThermostat(VeraDevice):
    """Class to represent a thermostat."""

    def set_temperature(self, temp: float) -> None:
        """Set current goal temperature / setpoint."""

        self.set_service_value(
            self.thermostat_setpoint, "CurrentSetpoint", "NewCurrentSetpoint", temp
        )

        self.set_cache_value("setpoint", temp)

    def get_current_goal_temperature(self, refresh: bool = False) -> Optional[float]:
        """Get current goal temperature / setpoint."""
        if refresh:
            self.refresh()
        try:
            return float(self.get_value("setpoint"))
        except (TypeError, ValueError):
            return None

    def get_current_temperature(self, refresh: bool = False) -> Optional[float]:
        """Get current temperature."""
        if refresh:
            self.refresh()
        try:
            return float(self.get_value("temperature"))
        except (TypeError, ValueError):
            return None

    def set_hvac_mode(self, mode: str) -> None:
        """Set the hvac mode."""
        self.set_service_value(
            self.thermostat_operating_service, "ModeTarget", "NewModeTarget", mode
        )
        self.set_cache_value("mode", mode)

    def get_hvac_mode(self, refresh: bool = False) -> Optional[str]:
        """Get the hvac mode."""
        if refresh:
            self.refresh()
        return cast(str, self.get_value("mode"))

    def turn_off(self) -> None:
        """Set hvac mode to off."""
        self.set_hvac_mode("Off")

    def turn_cool_on(self) -> None:
        """Set hvac mode to cool."""
        self.set_hvac_mode("CoolOn")

    def turn_heat_on(self) -> None:
        """Set hvac mode to heat."""
        self.set_hvac_mode("HeatOn")

    def turn_auto_on(self) -> None:
        """Set hvac mode to auto."""
        self.set_hvac_mode("AutoChangeOver")

    def set_fan_mode(self, mode: str) -> None:
        """Set the fan mode."""
        self.set_service_value(self.thermostat_fan_service, "Mode", "NewMode", mode)
        self.set_cache_value("fanmode", mode)

    def fan_on(self) -> None:
        """Turn fan on."""
        self.set_fan_mode("ContinuousOn")

    def fan_off(self) -> None:
        """Turn fan off."""
        self.set_fan_mode("Off")

    def get_fan_mode(self, refresh: bool = False) -> Optional[str]:
        """Get fan mode."""
        if refresh:
            self.refresh()
        return cast(str, self.get_value("fanmode"))

    def get_hvac_state(self, refresh: bool = False) -> Optional[str]:
        """Get current hvac state."""
        if refresh:
            self.refresh()
        return cast(str, self.get_value("hvacstate"))

    def fan_auto(self) -> None:
        """Set fan to automatic."""
        self.set_fan_mode("Auto")

    def fan_cycle(self) -> None:
        """Set fan to cycle."""
        self.set_fan_mode("PeriodicOn")


class VeraSceneController(VeraDevice):
    """Class to represent a scene controller."""

    def get_last_scene_id(self, refresh: bool = False) -> str:
        """Get last scene id.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        Refresh is only needed if you're not using subscriptions.
        """
        if refresh:
            self.refresh_complex_value("LastSceneID")
            self.refresh_complex_value("sl_CentralScene")
        val = self.get_complex_value("LastSceneID") or self.get_complex_value(
            "sl_CentralScene"
        )
        return cast(str, val)

    def get_last_scene_time(self, refresh: bool = False) -> str:
        """Get last scene time.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        Refresh is only needed if you're not using subscriptions.
        """
        if refresh:
            self.refresh_complex_value("LastSceneTime")
        val = self.get_complex_value("LastSceneTime")
        return cast(str, val)

    @property
    def should_poll(self) -> bool:
        """Determine if you should poll for data."""
        return True


class VeraScene:
    """Class to represent a scene that can be activated.

    This does not inherit from a VeraDevice since scene ids
    and device ids are separate sets.  A scene is not a device
    as far as Vera is concerned.

    TODO: The duplicated code between VeraScene & VeraDevice should
    be refactored at some point to be reused.  Perhaps a VeraObject?
    """

    def __init__(self, json_obj: dict, vera_controller: VeraController):
        """Init object."""
        self.json_state = json_obj
        self.scene_id = cast(int, self.json_state.get("id"))
        self.vera_controller = vera_controller
        self.name = self.json_state.get("name")
        self._active = False

        if not self.name:
            self.name = f"Vera Scene {self.name} {self.scene_id}"

    def __repr__(self) -> str:
        """Get a string representation."""
        return f"{self.__class__.__name__} (id={self.scene_id} name={self.name})"

    @property
    def scene_service(self) -> str:
        """Vera service string for switch."""
        return "urn:micasaverde-com:serviceId:HomeAutomationGateway1"

    def vera_request(self, **kwargs: str) -> requests.Response:
        """Perfom a vera_request for this scene."""
        request_payload = {"output_format": "json", "SceneNum": self.scene_id}
        request_payload.update(kwargs)

        return self.vera_controller.data_request(request_payload)

    def activate(self) -> None:
        """Activate a Vera scene.

        This will call the Vera api to activate a scene.
        """
        payload = {
            "id": "lu_action",
            "action": "RunScene",
            "serviceId": self.scene_service,
        }
        result = self.vera_request(**payload)
        LOG.debug(
            "activate: " "result of vera_request with payload %s: %s",
            payload,
            result.text,
        )

        self._active = True

    def update(self, params: dict) -> None:
        """Update the local variables."""
        self._active = params["active"] == 1

    def refresh(self) -> None:
        """Refresh the data used by get_value.

        Only needed if you're not using subscriptions.
        """
        j = self.vera_request(id="sdata", output_format="json").json()
        scenes = j.get("scenes")
        for scene_data in scenes:
            if scene_data.get("id") == self.scene_id:
                self.update(scene_data)

    @property
    def is_active(self) -> bool:
        """Is Scene active."""
        return self._active

    @property
    def vera_scene_id(self) -> int:
        """Return the ID Vera uses to refer to the scene."""
        return self.scene_id

    @property
    def should_poll(self) -> bool:
        """Whether polling is needed if using subscriptions for this device."""
        return True


class VeraGarageDoor(VeraSwitch):
    """Garage door device."""


class VeraAlert:
    """An alert triggered by variable state change."""

    def __init__(self, json_alert: dict, device: VeraDevice):
        """Init object."""
        self.device = device
        self.code = json_alert.get("Code")
        self.severity = json_alert.get("Severity")
        self.value = cast(str, json_alert.get("NewValue"))
        self.timestamp = datetime.fromtimestamp(json_alert.get("LocalTimestamp", 0))

    def __repr__(self) -> str:
        """Get a string representation."""
        return f"{self.__class__.__name__} (code={self.code} value={self.value} timestamp={self.timestamp})"


class PyveraError(Exception):
    """Simple error."""


class ControllerNotSetException(Exception):
    """The controller was not set in the subscription registry."""


class AbstractSubscriptionRegistry(ABC):
    """Class for subscribing to wemo events."""

    def __init__(self) -> None:
        """Init subscription."""
        self._devices: DefaultDict[int, List[VeraDevice]] = collections.defaultdict(
            list
        )
        self._callbacks: DefaultDict[
            VeraDevice, List[SubscriptionCallback]
        ] = collections.defaultdict(list)
        self._last_updated = TIMESTAMP_NONE
        self._controller: Optional[VeraController] = None

    def set_controller(self, controller: VeraController) -> None:
        """Set the controller."""
        self._controller = controller

    def get_controller(self) -> Optional[VeraController]:
        """Get the controller."""
        return self._controller

    def register(self, device: VeraDevice, callback: SubscriptionCallback) -> None:
        """Register a callback.

        device: device to be updated by subscription
        callback: callback for notification of changes
        """
        if not device:
            LOG.error("Received an invalid device: %r", device)
            return

        LOG.debug("Subscribing to events for %s", device.name)
        self._devices[device.vera_device_id].append(device)
        self._callbacks[device].append(callback)

    def unregister(self, device: VeraDevice, callback: SubscriptionCallback) -> None:
        """Remove a registered change callback.

        device: device that has the subscription
        callback: callback used in original registration
        """
        if not device:
            LOG.error("Received an invalid device: %r", device)
            return

        LOG.debug("Removing subscription for %s", device.name)
        self._callbacks[device].remove(callback)
        self._devices[device.vera_device_id].remove(device)

    def _event(
        self, device_data_list: List[dict], device_alert_list: List[dict]
    ) -> None:
        # Guard against invalid data from Vera API
        if not isinstance(device_data_list, list):
            LOG.debug("Got invalid device_data_list: %s", device_data_list)
            device_data_list = []

        if not isinstance(device_alert_list, list):
            LOG.debug("Got invalid device_alert_list: %s", device_alert_list)
            device_alert_list = []

        # Find unique device_ids that have data across both device_data and alert_data
        device_ids = set()

        for device_data in device_data_list:
            if "id" in device_data:
                device_ids.add(device_data["id"])
            else:
                LOG.debug("Got invalid device_data: %s", device_data)

        for alert_data in device_alert_list:
            if "PK_Device" in alert_data:
                device_ids.add(alert_data["PK_Device"])
            else:
                LOG.debug("Got invalid alert_data: %s", alert_data)

        for device_id in device_ids:
            try:
                device_list = self._devices.get(int(device_id), ())
                device_datas = [
                    data for data in device_data_list if data.get("id") == device_id
                ]
                device_alerts = [
                    alert
                    for alert in device_alert_list
                    if alert.get("PK_Device") == device_id
                ]

                device_data = device_datas[0] if device_datas else {}

                for device in device_list:
                    self._event_device(device, device_data, device_alerts)
            # pylint: disable=broad-except
            except Exception as exp:
                LOG.exception(
                    "Error processing event for device_id %s: %s", device_id, exp
                )

    def _event_device(
        self, device: Optional[VeraDevice], device_data: dict, device_alerts: List[dict]
    ) -> None:
        if device is None:
            return
        # Vera can send an update status STATE_NO_JOB but
        # with a comment about sending a command
        state = int(device_data.get("state", STATE_NOT_PRESENT))
        comment = device_data.get("comment", "")
        sending = comment.find("Sending") >= 0
        LOG.debug(
            "Event: %s, state %s, alerts %s, %s",
            device.name,
            state,
            len(device_alerts),
            json.dumps(device_data),
        )
        device.set_alerts(device_alerts)
        if sending and state == STATE_NO_JOB:
            state = STATE_JOB_WAITING_TO_START
        if state == STATE_JOB_IN_PROGRESS and device.__class__.__name__ == "VeraLock":
            # VeraLocks don't complete
            # so we detect if we are done from the comment field.
            # This is really just a workaround for a vera bug
            # and it does mean that a device name
            # cannot contain the SUCCESS! string (very unlikely)
            # since the name is also returned in the comment for
            # some status messages
            success = comment.find("SUCCESS!") >= 0
            if success:
                LOG.debug("Lock success found, job is done")
                state = STATE_JOB_DONE

        if state in (
            STATE_JOB_WAITING_TO_START,
            STATE_JOB_IN_PROGRESS,
            STATE_JOB_WAITING_FOR_CALLBACK,
            STATE_JOB_REQUEUE,
            STATE_JOB_PENDING_DATA,
        ):
            return
        if not (
            state == STATE_JOB_DONE
            or state == STATE_NOT_PRESENT
            or state == STATE_NO_JOB
            or (state == STATE_JOB_ERROR and comment.find("Setting user configuration"))
        ):
            LOG.error("Device %s, state %s, %s", device.name, state, comment)
            return
        device.update(device_data)
        for callback in self._callbacks.get(device, ()):
            try:
                callback(device)
            # pylint: disable=broad-except
            except Exception:
                # (Very) broad check to not let loosely-implemented callbacks
                # kill our polling thread. They should be catching their own
                # errors, so if it gets back to us, just log it and move on.
                LOG.exception(
                    "Unhandled exception in callback for device #%s (%s)",
                    str(device.device_id),
                    device.name,
                )

    @abstractmethod
    def start(self) -> None:
        """Start a thread to handle Vera blocked polling."""
        raise NotImplementedError("start method is not implemented.")

    @abstractmethod
    def stop(self) -> None:
        """Tell the subscription thread to terminate."""
        raise NotImplementedError("stop method is not implemented.")

    def get_device_data(self, last_updated: dict) -> ChangedDevicesValue:
        """Get device data."""
        if not self._controller:
            raise ControllerNotSetException()

        return self._controller.get_changed_devices(last_updated)

    def get_alert_data(self, last_updated: dict) -> List[dict]:
        """Get alert data."""
        if not self._controller:
            raise ControllerNotSetException()

        return self._controller.get_alerts(last_updated)

    def always_update(self) -> bool:  # pylint: disable=no-self-use
        """Determine if we should treat every poll as a data change."""
        return False

    def poll_server_once(self) -> bool:
        """Poll the vera server only once.

        Returns True if it could successfully check for data. False otherwise.
        """
        device_data: List[dict] = []
        alert_data: List[dict] = []
        data_changed = False
        try:
            LOG.debug("Polling for Vera changes")
            device_data, new_timestamp = self.get_device_data(self._last_updated)
            if (
                new_timestamp["dataversion"] != self._last_updated["dataversion"]
                or self.always_update()
            ):
                alert_data = self.get_alert_data(self._last_updated)
                data_changed = True
            else:
                data_changed = False
            self._last_updated = new_timestamp
        except requests.RequestException as ex:
            LOG.debug("Caught RequestException: %s", str(ex))
        except PyveraError as ex:
            LOG.debug("Non-fatal error in poll: %s", str(ex))
        except Exception as ex:
            LOG.exception("Vera poll thread general exception: %s", str(ex))
            raise
        else:
            LOG.debug("Poll returned")
            if data_changed or self.always_update():
                self._event(device_data, alert_data)
            else:
                LOG.debug("No changes in poll interval")

            return True

        # After error, discard timestamp for fresh update. pyvera issue #89
        self._last_updated = {"dataversion": 1, "loadtime": 0}
        LOG.info("Could not poll Vera")
        return False


class SubscriptionRegistry(AbstractSubscriptionRegistry):
    """Class for subscribing to wemo events."""

    def __init__(self) -> None:
        """Init subscription."""
        super(SubscriptionRegistry, self).__init__()
        self._exiting = threading.Event()
        self._poll_thread: threading.Thread

    def join(self) -> None:
        """Don't allow the main thread to terminate until we have."""
        self._poll_thread.join()

    def start(self) -> None:
        """Start a thread to handle Vera blocked polling."""
        self._poll_thread = threading.Thread(
            target=self._run_poll_server, name="Vera Poll Thread"
        )
        self._exiting = threading.Event()
        self._poll_thread.daemon = True
        self._poll_thread.start()

    def stop(self) -> None:
        """Tell the subscription thread to terminate."""
        if self._exiting:
            self._exiting.set()
        self.join()
        LOG.info("Terminated thread")

    def _run_poll_server(self) -> None:
        while not self._exiting.wait(timeout=1):
            if not self.poll_server_once():
                self._exiting.wait(timeout=SUBSCRIPTION_RETRY)

        LOG.info("Shutdown Vera Poll Thread")
