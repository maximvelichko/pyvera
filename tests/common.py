"""Common code for tests."""

from copy import deepcopy
from typing import Any, NamedTuple, Optional

from pyvera import (
    CATEGORY_ARMABLE,
    CATEGORY_CURTAIN,
    CATEGORY_DIMMER,
    CATEGORY_GENERIC,
    CATEGORY_HUMIDITY_SENSOR,
    CATEGORY_LIGHT_SENSOR,
    CATEGORY_LOCK,
    CATEGORY_POWER_METER,
    CATEGORY_SCENE_CONTROLLER,
    CATEGORY_SENSOR,
    CATEGORY_SWITCH,
    CATEGORY_TEMPERATURE_SENSOR,
    CATEGORY_THERMOSTAT,
    CATEGORY_UV_SENSOR,
    VeraController,
)

VeraApiData = NamedTuple(
    "VeraApiData", [("sdata", dict), ("status", dict), ("lu_sdata", dict)],
)

VeraControllerData = NamedTuple(
    "ControllerData", [("api_data", VeraApiData), ("controller", VeraController)]
)


def new_vera_api_data():
    return VeraApiData(
        sdata=deepcopy(RESPONSE_SDATA),
        status=deepcopy(RESPONSE_STATUS),
        lu_sdata=deepcopy(RESPONSE_LU_SDATA_EMPTY),
    )


def find_device_object(device_id: int, data_list: list) -> Optional[dict]:
    """Find a vera device object in a list of devices."""
    for device in data_list or []:
        if device.get("id") == device_id:
            return device

    return None


def get_device(device_id: int, api_data: VeraApiData) -> Optional[dict]:
    """Find a vera device."""
    return find_device_object(device_id, api_data.sdata.get("devices"))


def get_device_status(device_id: int, api_data: VeraApiData) -> Optional[dict]:
    """Find a vera device status."""
    return find_device_object(device_id, api_data.status.get("devices"))


def set_device_status(device_id: int, api_data: VeraApiData, key: str, value: Any):
    device = get_device(device_id, api_data)
    device_status = get_device_status(device_id)

    device_status[key] = value
    device[key] = value

    device_status["states"] = device_status["states"] or []

    # Get the current state or create a new one.
    state = next([s for s in device_status["states"] if s["variable"] == key]) or {}

    # Update current states to exclude the one we are changing.
    device_status["states"] = [
        s for s in device_status["states"] if s["variable"] != key
    ]

    # Add the updated state to the list of states.
    device_status["state"].append(state.update({"variable": key, "value": value}))


def get_device_state(device_id: int, api_data: VeraApiData, key: str) -> Optional[dict]:
    device_status = get_device_status(device_id)
    for state in device_status.get("states", []):
        if state.get("variable") == key:
            return state

    return None


def update_device(
    controller_data: VeraControllerData, device_id: int, key: str, value: Any
) -> None:
    """Update a vera device with a specific key/value."""
    device = get_device(device_id, controller_data.api_data)
    assert device, "Failed to find device with device id %d" % device_id

    device_status = get_device_status(device_id, controller_data.api_data)
    assert device_status, "Failed to find device status with device id %d" % device_id

    device_status[key] = value
    device[key] = value

    device_status["states"] = device_status["states"] or []

    # Get the current state or create a new one.
    state = next(iter([s for s in device_status["states"] if s["variable"] == key]), {})

    # Update current states to exclude the one we are changing.
    device_status["states"] = [
        s for s in device_status["states"] if s["variable"] != key
    ]

    # Add the updated state to the list of states.
    state.update({"variable": key, "value": value})
    device_status["states"].append(state)

    publish_device_status(controller_data.controller, device_status)


def publish_device_status(controller: VeraController, device_status: dict) -> None:
    """Instruct pyvera to notify objects that data changed for a device."""
    # pylint: disable=protected-access
    controller.subscription_registry._event([device_status], [])


def new_mocked_controller(api_data: VeraApiData = None):
    def data_request(payload: dict, timeout=5):
        nonlocal api_data
        payload_id = payload.get("id")

        if payload_id == "sdata":
            return ResponseStub(json=api_data.sdata)
        if payload_id == "status":
            return ResponseStub(json=api_data.status)
        if payload_id == "lu_sdata":
            return ResponseStub(json=api_data.lu_sdata)
        if payload_id == "action":
            return ResponseStub(json={})
        if payload_id == "variableget":
            device_id = int(payload.get("DeviceNum"))
            variable = payload.get("Variable")

            status = get_device_status(device_id, api_data)
            for state in status.get("states", []):
                if state.get("variable") == variable:
                    # return state.get("value")
                    return ResponseStub(text=state.get("value"))

            return ResponseStub(text="")
        if payload_id == "lu_action":
            params = payload.copy()
            params.pop("id")
            service_id = params.pop("serviceId")
            action = params.pop("action")
            device_id = int(params.pop("DeviceNum"))
            params.pop("output_format")
            set_state_variable_name = next(
                key for key in params if key.lower().startswith("new")
            )
            state_variable_name = set_state_variable_name[3:]
            state_variable_value = params.pop(set_state_variable_name)
            status_variable_name = None

            if service_id == "urn:upnp-org:serviceId:SwitchPower1":
                if action == "SetTarget":
                    status_variable_name = "status"
            elif service_id == "urn:upnp-org:serviceId:Dimming1":
                if action == "SetLoadLevelTarget":
                    status_variable_name = "level"
            elif service_id == "urn:micasaverde-com:serviceId:SecuritySensor1":
                if action == "SetArmed":
                    status_variable_name = "armed"
            elif service_id == "urn:upnp-org:serviceId:WindowCovering1":
                if action == "SetLoadLevelTarget":
                    status_variable_name = "level"
            elif service_id == "urn:micasaverde-com:serviceId:DoorLock1":
                if action == "NewTarget":
                    status_variable_name = "locked"
            elif service_id == "urn:upnp-org:serviceId:HVAC_UserOperatingMode1":
                if action == "SetModeTarget":
                    status_variable_name = "mode"
            elif service_id == "urn:upnp-org:serviceId:HVAC_FanOperatingMode1":
                if action == "SetMode":
                    status_variable_name = "fanmode"
            elif service_id == "urn:upnp-org:serviceId:TemperatureSetpoint1_Cool":
                pass
            elif service_id == "urn:upnp-org:serviceId:TemperatureSetpoint1_Heat":
                pass
            elif service_id == "urn:upnp-org:serviceId:TemperatureSetpoint1":
                if action == "SetCurrentSetpoint":
                    status_variable_name = "setpoint"
            elif service_id == "urn:micasaverde-com:serviceId:Color1":
                if action == "SetColorRGB":
                    status_variable_name = "CurrentColor"

            device = get_device(device_id, api_data)
            status = get_device_status(device_id, api_data)

            # Update the device and status objects.
            if status_variable_name is not None:
                device[status_variable_name] = state_variable_value
                status[status_variable_name] = state_variable_value

            # Update the state object.
            status["states"] = [
                state
                for state in status.get("states", [])
                if state.get("service") != service_id
                or state.get("variable") != state_variable_name
            ]
            status["states"].append(
                {
                    "service": service_id,
                    "variable": state_variable_name,
                    "value": state_variable_value,
                }
            )

            return ResponseStub(json={})

        return ResponseStub(json={})

    controller = VeraController("http://127.0.0.1:123")
    controller.data_request = data_request

    return VeraControllerData(api_data=api_data, controller=controller)


class ResponseStub:
    """Simple stub."""

    def __init__(self, json=None, text=None):
        """Init object."""
        self._json = json
        self._text = text

    def json(self) -> Any:
        """Get json."""
        return self._json

    @property
    def text(self) -> str:
        """Get text."""
        return self._text


class ControllerConfig:
    def __init__(self, sdata, status, lu_sdata):
        self.sdata = sdata
        self.status = status
        self.lu_sdata = lu_sdata


RESPONSE_SDATA_EMPTY = {"scenes": (), "categories": (), "devices": ()}
RESPONSE_STATUS_EMPTY = {"devices": ()}
RESPONSE_LU_SDATA_EMPTY = {}
RESPONSE_DEVICES_EMPTY = {}
RESPONSE_SCENES_EMPTY = {}

SCENE1_ID = 101

DEVICE_IGNORE = 55
DEVICE_ALARM_SENSOR_ID = 62
DEVICE_DOOR_SENSOR_ID = 45
DEVICE_MOTION_SENSOR_ID = 51
DEVICE_TEMP_SENSOR_ID = 52
DEVICE_DIMMER_ID = 59
DEVICE_LIGHT_ID = 69
DEVICE_SWITCH_ID = 44
DEVICE_SWITCH2_ID = 46
DEVICE_LOCK_ID = 10
DEVICE_THERMOSTAT_ID = 11
DEVICE_CURTAIN_ID = 12
DEVICE_SCENE_CONTROLLER_ID = 13
DEVICE_LIGHT_SENSOR_ID = 14
DEVICE_UV_SENSOR_ID = 15
DEVICE_HUMIDITY_SENSOR_ID = 16
DEVICE_POWER_METER_SENSOR_ID = 17

CATEGORY_UNKNOWN = 1234

RESPONSE_SDATA = {
    "scenes": [{"id": SCENE1_ID, "name": "scene1", "active": 0, "root": 0}],
    "temperature": 23,
    "categories": [
        {"name": "Dimmable Switch", "id": CATEGORY_DIMMER},
        {"name": "On/Off Switch", "id": CATEGORY_SWITCH},
        {"name": "Sensor", "id": CATEGORY_ARMABLE},
        {"name": "Generic IO", "id": CATEGORY_GENERIC},
        {"name": "Temperature Sensor", "id": CATEGORY_TEMPERATURE_SENSOR},
        {"name": "Lock", "id": CATEGORY_LOCK},
        {"name": "Thermostat", "id": CATEGORY_THERMOSTAT},
        {"name": "Light sensor", "id": CATEGORY_LIGHT_SENSOR},
        {"name": "UV sensor", "id": CATEGORY_UV_SENSOR},
        {"name": "Humidity sensor", "id": CATEGORY_HUMIDITY_SENSOR},
        {"name": "Power meter", "id": CATEGORY_POWER_METER},
    ],
    "devices": [
        {
            "name": "Ignore 1",
            "altid": "6",
            "id": DEVICE_IGNORE,
            "category": CATEGORY_SWITCH,
            "subcategory": 1,
            "room": 0,
            "parent": 1,
            "armed": "0",
            "armedtripped": "0",
            "configured": "1",
            "batterylevel": "100",
            "commFailure": "0",
            "lasttrip": "1571790666",
            "tripped": "0",
            "state": -1,
            "comment": "",
        },
        {
            "name": "Door sensor 1",
            "altid": "6",
            "id": DEVICE_DOOR_SENSOR_ID,
            "category": CATEGORY_ARMABLE,
            "subcategory": 1,
            "room": 0,
            "parent": 1,
            "armed": "0",
            "armedtripped": "0",
            "configured": "1",
            "batterylevel": "100",
            "commFailure": "0",
            "lasttrip": "1571790666",
            "tripped": "0",
            "state": -1,
            "comment": "",
        },
        {
            "name": "Motion sensor 1",
            "altid": "12",
            "id": DEVICE_MOTION_SENSOR_ID,
            "category": CATEGORY_ARMABLE,
            "subcategory": 3,
            "room": 0,
            "parent": 1,
            "armed": "0",
            "armedtripped": "0",
            "configured": "1",
            "batterylevel": "100",
            "commFailure": "0",
            "lasttrip": "1571975359",
            "tripped": "0",
            "state": -1,
            "comment": "",
        },
        {
            "name": "Temp sensor 1",
            "altid": "m1",
            "id": DEVICE_TEMP_SENSOR_ID,
            "category": CATEGORY_TEMPERATURE_SENSOR,
            "subcategory": 0,
            "room": 0,
            "parent": 51,
            "configured": "0",
            "temperature": "57.00",
        },
        {
            "name": "Dimmer 1",
            "altid": "16",
            "id": DEVICE_DIMMER_ID,
            "category": CATEGORY_DIMMER,
            "subcategory": 2,
            "room": 0,
            "parent": 1,
            "kwh": "0.0000",
            "watts": "0",
            "configured": "1",
            "level": "0",
            "status": "0",
            "state": -1,
            "comment": "",
        },
        {
            "name": "Light 1",
            "altid": "16",
            "id": DEVICE_LIGHT_ID,
            "category": CATEGORY_DIMMER,
            "subcategory": 2,
            "room": 0,
            "parent": 1,
            "kwh": "0.0000",
            "watts": "0",
            "configured": "1",
            "level": "0",
            "status": "0",
            "state": -1,
            "comment": "",
        },
        {
            "name": "Switch 1",
            "altid": "5",
            "id": DEVICE_SWITCH_ID,
            "category": CATEGORY_SWITCH,
            "subcategory": 0,
            "room": 0,
            "parent": 1,
            "configured": "1",
            "commFailure": "0",
            "armedtripped": "1",
            "lasttrip": "1561049427",
            "tripped": "1",
            "armed": "0",
            "status": "0",
            "state": -1,
            "comment": "",
        },
        {
            "name": "Switch 2",
            "altid": "5",
            "id": DEVICE_SWITCH2_ID,
            "category": CATEGORY_SWITCH,
            "subcategory": 0,
            "room": 0,
            "parent": 1,
            "configured": "1",
            "commFailure": "0",
            "armedtripped": "1",
            "lasttrip": "1561049427",
            "tripped": "1",
            "armed": "0",
            "status": "0",
            "state": -1,
            "comment": "",
        },
        {
            "name": "Lock 1",
            "altid": "5",
            "id": DEVICE_LOCK_ID,
            "category": CATEGORY_LOCK,
            "subcategory": 0,
            "room": 0,
            "parent": 1,
            "configured": "1",
            "commFailure": "0",
            "armedtripped": "1",
            "lasttrip": "1561049427",
            "tripped": "1",
            "armed": "0",
            "status": "0",
            "state": -1,
            "comment": "",
            "locked": "0",
        },
        {
            "name": "Thermostat 1",
            "altid": "5",
            "id": DEVICE_THERMOSTAT_ID,
            "category": CATEGORY_THERMOSTAT,
            "subcategory": 0,
            "room": 0,
            "parent": 1,
            "configured": "1",
            "commFailure": "0",
            "armedtripped": "1",
            "lasttrip": "1561049427",
            "tripped": "1",
            "armed": "0",
            "status": "0",
            "state": -1,
            "mode": "Off",
            "fanmode": "Off",
            "hvacstate": "Off",
            "setpoint": 8,
            "temperature": 9,
            "watts": 23,
            "comment": "",
        },
        {
            "name": "Curtain 1",
            "altid": "5",
            "id": DEVICE_CURTAIN_ID,
            "category": CATEGORY_CURTAIN,
            "subcategory": 0,
            "room": 0,
            "parent": 1,
            "configured": "1",
            "commFailure": "0",
            "armedtripped": "1",
            "lasttrip": "1561049427",
            "tripped": "1",
            "armed": "0",
            "status": "0",
            "state": -1,
            "level": 0,
            "comment": "",
        },
        {
            "name": "Scene 1",
            "altid": "5",
            "id": DEVICE_SCENE_CONTROLLER_ID,
            "category": CATEGORY_SCENE_CONTROLLER,
            "subcategory": 0,
            "room": 0,
            "parent": 1,
            "configured": "1",
            "commFailure": "0",
            "armedtripped": "1",
            # "lasttrip": "1561049427",
            "tripped": "1",
            "armed": "0",
            "status": "0",
            "state": -1,
            "active": 0,
            "comment": "",
        },
        {
            "name": "Alarm sensor 1",
            "altid": "18",
            "id": DEVICE_ALARM_SENSOR_ID,
            "category": CATEGORY_SENSOR,
            "subcategory": 0,
            "room": 0,
            "parent": 1,
            "configured": "1",
            "batterylevel": "100",
            "commFailure": "0",
            "armed": "0",
            "armedtripped": "0",
            "state": -1,
            "tripped": "0",
            "comment": "",
        },
        {
            "name": "Light sensor 1",
            "altid": "5",
            "id": DEVICE_LIGHT_SENSOR_ID,
            "category": CATEGORY_LIGHT_SENSOR,
            "subcategory": 0,
            "room": 0,
            "parent": 1,
            "configured": "1",
            "commFailure": "0",
            "armedtripped": "1",
            "lasttrip": "1561049427",
            "tripped": "1",
            "armed": "0",
            "status": "0",
            "state": -1,
            "light": "0",
            "comment": "",
        },
        {
            "name": "UV sensor 1",
            "altid": "5",
            "id": DEVICE_UV_SENSOR_ID,
            "category": CATEGORY_UV_SENSOR,
            "subcategory": 0,
            "room": 0,
            "parent": 1,
            "configured": "1",
            "commFailure": "0",
            "armedtripped": "1",
            "lasttrip": "1561049427",
            "tripped": "1",
            "armed": "0",
            "status": "0",
            "state": -1,
            "light": "0",
            "comment": "",
        },
        {
            "name": "Humidity sensor 1",
            "altid": "5",
            "id": DEVICE_HUMIDITY_SENSOR_ID,
            "category": CATEGORY_HUMIDITY_SENSOR,
            "subcategory": 0,
            "room": 0,
            "parent": 1,
            "configured": "1",
            "commFailure": "0",
            "armedtripped": "1",
            "lasttrip": "1561049427",
            "tripped": "1",
            "armed": "0",
            "status": "0",
            "state": -1,
            "humidity": "0",
            "comment": "",
        },
        {
            "name": "Power meter sensor 1",
            "altid": "5",
            "id": DEVICE_POWER_METER_SENSOR_ID,
            "category": CATEGORY_POWER_METER,
            "subcategory": 0,
            "room": 0,
            "parent": 1,
            "configured": "1",
            "commFailure": "0",
            "armedtripped": "1",
            "lasttrip": "1561049427",
            "tripped": "1",
            "armed": "0",
            "status": "0",
            "state": -1,
            "watts": "0",
            "comment": "",
        },
    ],
}

RESPONSE_STATUS = {
    "startup": {"tasks": []},
    "devices": [
        {
            "id": DEVICE_DOOR_SENSOR_ID,
            "states": [],
            "Jobs": [],
            "PendingJobs": 0,
            "tooltip": {"display": 0},
            "armed": "0",
        },
        {
            "id": DEVICE_MOTION_SENSOR_ID,
            "states": [],
            "Jobs": [],
            "PendingJobs": 0,
            "tooltip": {"display": 0},
            "armed": "0",
        },
        {
            "id": DEVICE_TEMP_SENSOR_ID,
            "states": [],
            "Jobs": [],
            "PendingJobs": 0,
            "tooltip": {"display": 0},
            "status": -1,
        },
        {
            "id": DEVICE_DIMMER_ID,
            "states": [],
            "Jobs": [],
            "PendingJobs": 0,
            "tooltip": {"display": 0},
            "status": -1,
        },
        {
            "id": DEVICE_LIGHT_ID,
            "states": [
                {
                    "service": "urn:micasaverde-com:serviceId:Color1",
                    "variable": "CurrentColor",
                    "value": "I=0,A=0,R=255,G=100,B=100",
                },
                {
                    "service": "urn:micasaverde-com:serviceId:Color1",
                    "variable": "SupportedColors",
                    "value": "I,A,R,G,B",
                },
            ],
            "Jobs": [],
            "PendingJobs": 0,
            "tooltip": {"display": 0},
            "status": -1,
        },
        {
            "id": DEVICE_SWITCH_ID,
            "states": [],
            "Jobs": [],
            "PendingJobs": 0,
            "tooltip": {"display": 0},
            "status": -1,
        },
        {
            "id": DEVICE_SWITCH2_ID,
            "states": [],
            "Jobs": [],
            "PendingJobs": 0,
            "tooltip": {"display": 0},
            "status": -1,
        },
        {
            "id": DEVICE_LOCK_ID,
            "states": [],
            "Jobs": [],
            "PendingJobs": 0,
            "tooltip": {"display": 0},
            "status": -1,
            "locked": "0",
        },
        {
            "id": DEVICE_THERMOSTAT_ID,
            "states": [],
            "Jobs": [],
            "PendingJobs": 0,
            "tooltip": {"display": 0},
            "status": -1,
        },
        {
            "id": DEVICE_CURTAIN_ID,
            "states": [],
            "Jobs": [],
            "PendingJobs": 0,
            "tooltip": {"display": 0},
            "status": -1,
        },
        {
            "id": DEVICE_SCENE_CONTROLLER_ID,
            "states": [
                {"service": "", "variable": "LastSceneID", "value": "1234"},
                {"service": "", "variable": "LastSceneTime", "value": "10000012"},
            ],
            "Jobs": [],
            "PendingJobs": 0,
            "tooltip": {"display": 0},
            "status": -1,
        },
        {
            "id": DEVICE_ALARM_SENSOR_ID,
            "states": [],
            "Jobs": [],
            "PendingJobs": 0,
            "tooltip": {"display": 0},
            "status": -1,
        },
        {
            "id": DEVICE_LIGHT_SENSOR_ID,
            "states": [],
            "Jobs": [],
            "PendingJobs": 0,
            "tooltip": {"display": 0},
            "status": -1,
        },
        {
            "id": DEVICE_UV_SENSOR_ID,
            "states": [],
            "Jobs": [],
            "PendingJobs": 0,
            "tooltip": {"display": 0},
            "status": -1,
        },
        {
            "id": DEVICE_HUMIDITY_SENSOR_ID,
            "states": [],
            "Jobs": [],
            "PendingJobs": 0,
            "tooltip": {"display": 0},
            "status": -1,
        },
        {
            "id": DEVICE_POWER_METER_SENSOR_ID,
            "states": [],
            "Jobs": [],
            "PendingJobs": 0,
            "tooltip": {"display": 0},
            "status": -1,
        },
    ],
}

RESPONSE_SCENES = {}
