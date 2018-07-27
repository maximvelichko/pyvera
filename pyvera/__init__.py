"""
Vera Controller Python API.

This lib is designed to simplify communication with Vera controllers
"""
import logging
import requests
import sys
import json
import os

from .subscribe import SubscriptionRegistry
from .subscribe import PyveraError

__author__ = 'jamespcole'

# Time to block on Vera poll if there are no changes in seconds
SUBSCRIPTION_WAIT = 30
# Min time to wait for event in miliseconds
SUBSCRIPTION_MIN_WAIT = 200
# Timeout for requests calls, as vera sometimes just sits on sockets.
TIMEOUT = SUBSCRIPTION_WAIT

CATEGORY_DIMMER = 2
CATEGORY_SWITCH = 3
CATEGORY_ARMABLE = 4
CATEGORY_THERMOSTAT = 5
CATEGORY_LOCK = 7
CATEGORY_CURTAIN = 8
CATEGORY_REMOTE = 9
CATEGORY_SENSOR = 12
CATEGORY_SCENE_CONTROLLER = 14
CATEGORY_HUMIDITY_SENSOR = 16
CATEGORY_TEMPERATURE_SENSOR = 17
CATEGORY_LIGHT_SENSOR = 18
CATEGORY_POWER_METER = 21
CATEGORY_VERA_SIREN = 24
CATEGORY_UV_SENSOR = 28

_VERA_CONTROLLER = None

# Set up the console logger for debugging
logger = logging.getLogger(__name__)
# Set logging level (such as INFO, DEBUG, etc) via an environment variable
# Defaults to WARNING log level unless PYVERA_LOGLEVEL variable exists
logger_level = os.environ.get("PYVERA_LOGLEVEL", None)
if logger_level:
    logger.setLevel(logger_level)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('%(levelname)s@{%(name)s:%(lineno)d} - %(message)s'))
    logger.addHandler(ch)
logger.debug("DEBUG logging is ON")

def init_controller(url):
    """Initialize a controller.

    Provides a single global controller for applications that can't do this
    themselves
    """
    # pylint: disable=global-statement
    global _VERA_CONTROLLER
    created = False
    if _VERA_CONTROLLER is None:
        _VERA_CONTROLLER = VeraController(url)
        created = True
        _VERA_CONTROLLER.start()
    return [_VERA_CONTROLLER, created]


def get_controller():
    """Return the global controller from init_controller."""
    return _VERA_CONTROLLER


class VeraController(object):
    """Class to interact with the Vera device."""

    # pylint: disable=too-many-instance-attributes
    temperature_units = 'C'

    def __init__(self, base_url):
        """Setup Vera controller at the given URL.

        base_url: Vera API URL, eg http://vera:3480.
        """
        self.base_url = base_url
        self.devices = []
        self.scenes = []
        self.temperature_units = 'C'
        self.version = None
        self.model = None
        self.serial_number = None
        self.device_services_map = None
        self.subscription_registry = SubscriptionRegistry()
        self.categories = {}
        self.device_id_map = {}

    def data_request(self, payload, timeout=TIMEOUT):
        """Perform a data_request and return the result."""
        request_url = self.base_url + "/data_request"
        return requests.get(request_url, timeout=timeout, params=payload)

    def get_simple_devices_info(self):
        """Get basic device info from Vera."""
        j = self.data_request({'id': 'sdata'}).json()

        self.scenes = []
        items = j.get('scenes')

        for item in items:
            self.scenes.append(VeraScene(item, self))

        if j.get('temperature'):
            self.temperature_units = j.get('temperature')

        self.categories = {}
        cats = j.get('categories')

        for cat in cats:
            self.categories[cat.get('id')] = cat.get('name')

        self.device_id_map = {}

        devs = j.get('devices')
        for dev in devs:
            dev['categoryName'] = self.categories.get(dev.get('category'))
            self.device_id_map[dev.get('id')] = dev

    def get_scenes(self):
        """Get list of scenes."""

        self.get_simple_devices_info()

        return self.scenes

    def get_device_by_name(self, device_name):
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
            logger.debug('Did not find device with {}'.format(device_name))

        return found_device

    def get_device_by_id(self, device_id):
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
            logger.debug('Did not find device with {}'.format(device_id))

        return found_device

    def get_devices(self, category_filter=''):
        """Get list of connected devices.

        category_filter param is an array of strings
        """
        # pylint: disable=too-many-branches

        # the Vera rest API is a bit rough so we need to make 2 calls to get
        # all the info e need
        self.get_simple_devices_info()

        j = self.data_request({'id': 'status', 'output_format': 'json'}).json()

        self.devices = []
        items = j.get('devices')

        for item in items:
            item['deviceInfo'] = self.device_id_map.get(item.get('id'))
            if item.get('deviceInfo'):
                device_category = item.get('deviceInfo').get('category')
                if device_category == CATEGORY_DIMMER:
                    device = VeraDimmer(item, self)
                elif ( device_category == CATEGORY_SWITCH or
                       device_category == CATEGORY_VERA_SIREN):
                    device = VeraSwitch(item, self)
                elif device_category == CATEGORY_THERMOSTAT:
                    device = VeraThermostat(item, self)
                elif device_category == CATEGORY_LOCK:
                    device = VeraLock(item, self)
                elif device_category == CATEGORY_CURTAIN:
                    device = VeraCurtain(item, self)
                elif device_category == CATEGORY_ARMABLE:
                    device = VeraBinarySensor(item, self)
                elif (device_category == CATEGORY_SENSOR or
                      device_category == CATEGORY_HUMIDITY_SENSOR or
                      device_category == CATEGORY_TEMPERATURE_SENSOR or
                      device_category == CATEGORY_LIGHT_SENSOR or
                      device_category == CATEGORY_POWER_METER or
                      device_category == CATEGORY_UV_SENSOR):
                    device = VeraSensor(item, self)
                elif (device_category == CATEGORY_SCENE_CONTROLLER or
                      device_category == CATEGORY_REMOTE):
                    device = VeraSceneController(item, self)
                else:
                    device = VeraDevice(item, self)
                self.devices.append(device)
                if (device.is_armable and not (
                    device_category == CATEGORY_SWITCH or
                    device_category == CATEGORY_VERA_SIREN)):
                    self.devices.append(VeraArmableDevice(item, self))
            else:
                self.devices.append(VeraDevice(item, self))

        if not category_filter:
            return self.devices

        devices = []
        for device in self.devices:
            if (device.category_name is not None and
                    device.category_name != '' and
                    device.category_name in category_filter):
                devices.append(device)
        return devices

    def refresh_data(self):
        """Refresh data from Vera device."""
        j = self.data_request({'id': 'sdata'}).json()

        self.temperature_units = j.get('temperature', 'C')
        self.model = j.get('model')
        self.version = j.get('version')
        self.serial_number = j.get('serial_number')

        categories = {}
        cats = j.get('categories')

        for cat in cats:
            categories[cat.get('id')] = cat.get('name')

        device_id_map = {}

        devs = j.get('devices')
        for dev in devs:
            dev['categoryName'] = categories.get(dev.get('category'))
            device_id_map[dev.get('id')] = dev

        return device_id_map

    def map_services(self):
        """Get full Vera device service info."""
        # the Vera rest API is a bit rough so we need to make 2 calls
        # to get all the info e need
        self.get_simple_devices_info()

        j = self.data_request({'id': 'status', 'output_format': 'json'}).json()

        service_map = {}

        items = j.get('devices')

        for item in items:
            service_map[item.get('id')] = item.get('states')

        self.device_services_map = service_map

    def get_changed_devices(self, timestamp):
        """Get data since last timestamp.

        This is done via a blocking call, pass NONE for initial state.
        """
        if timestamp is None:
            payload = {}
        else:
            payload = {
                'timeout': SUBSCRIPTION_WAIT,
                'minimumdelay': SUBSCRIPTION_MIN_WAIT
            }
            payload.update(timestamp)
        # double the timeout here so requests doesn't timeout before vera
        payload.update({
            'id': 'lu_sdata',
        })

        logger.debug("get_changed_devices() requesting payload %s", str(payload))
        r = self.data_request(payload, TIMEOUT*2)
        r.raise_for_status()

        # If the Vera disconnects before writing a full response (as lu_sdata
        # will do when interrupted by a Luup reload), the requests module will
        # happily return 200 with an empty string. So, test for empty response,
        # so we don't rely on the JSON parser to throw an exception.
        if r.text == "":
            raise PyveraError("Empty response from Vera")

        # Catch a wide swath of what the JSON parser might throw, within
        # reason. Unfortunately, some parsers don't specifically return
        # json.decode.JSONDecodeError, but so far most seem to derive what
        # they do throw from ValueError, so that's helpful.
        try:
            result = r.json()
        except ValueError as ex:
            raise PyveraError("JSON decode error: " + str(ex))

        if not ( type(result) is dict
                 and 'loadtime' in result and 'dataversion' in result ):
            raise PyveraError("Unexpected/garbled response from Vera")

        # At this point, all good. Update timestamp and return change data.
        device_data = result.get('devices')
        timestamp = {
            'loadtime': result.get('loadtime'),
            'dataversion': result.get('dataversion')
        }
        return [device_data, timestamp]

    def start(self):
        """Start the subscription thread."""
        self.subscription_registry.start()

    def stop(self):
        """Stop the subscription thread."""
        self.subscription_registry.stop()

    def register(self, device, callback):
        """Register a device and callback with the subscription service."""
        self.subscription_registry.register(device, callback)

    def unregister(self, device, callback):
        """Unregister a device and callback with the subscription service."""
        self.subscription_registry.unregister(device, callback)


class VeraDevice(object):  # pylint: disable=R0904
    """ Class to represent each vera device."""

    def __init__(self, json_obj, vera_controller):
        """Setup a Vera device."""
        self.json_state = json_obj
        self.device_id = self.json_state.get('id')
        self.vera_controller = vera_controller
        self.name = ''

        if self.json_state.get('deviceInfo'):
            self.category = self.json_state.get('deviceInfo').get('category')
            self.category_name = (
                self.json_state.get('deviceInfo').get('categoryName'))
            self.name = self.json_state.get('deviceInfo').get('name')
        else:
            self.category_name = ''

        if not self.name:
            if self.category_name:
                self.name = ('Vera ' + self.category_name +
                             ' ' + str(self.device_id))
            else:
                self.name = 'Vera Device ' + str(self.device_id)

    def __repr__(self):
        if sys.version_info >= (3, 0):
            return "{} (id={} category={} name={})".format(
                self.__class__.__name__,
                self.device_id,
                self.category_name,
                self.name)
        else:
            return u"{} (id={} category={} name={})".format(
                self.__class__.__name__,
                self.device_id,
                self.category_name,
                self.name).encode('utf-8')

    @property
    def switch_service(self):
        """Vera service string for switch."""
        return 'urn:upnp-org:serviceId:SwitchPower1'

    @property
    def dimmer_service(self):
        """Vera service string for dimmer."""
        return 'urn:upnp-org:serviceId:Dimming1'

    @property
    def security_sensor_service(self):
        """Vera service string for armable sensors."""
        return 'urn:micasaverde-com:serviceId:SecuritySensor1'

    @property
    def window_covering_service(self):
        """Vera service string for window covering service."""
        return 'urn:upnp-org:serviceId:WindowCovering1'

    @property
    def lock_service(self):
        """Vera service string for lock service."""
        return 'urn:micasaverde-com:serviceId:DoorLock1'

    @property
    def thermostat_operating_service(self):
        """Vera service string HVAC operating mode."""
        return 'urn:upnp-org:serviceId:HVAC_UserOperatingMode1',

    @property
    def thermostat_fan_service(self):
        """Vera service string HVAC fan operating mode."""
        return 'urn:upnp-org:serviceId:HVAC_FanOperatingMode1'

    @property
    def thermostat_cool_setpoint(self):
        """Vera service string Temperature Setpoint1 Cool."""
        return 'urn:upnp-org:serviceId:TemperatureSetpoint1_Cool'

    @property
    def thermostat_heat_setpoint(self):
        """Vera service string Temperature Setpoint Heat."""
        return 'urn:upnp-org:serviceId:TemperatureSetpoint1_Heat'

    @property
    def thermostat_setpoint(self):
        """Vera service string Temperature Setpoint."""
        return 'urn:upnp-org:serviceId:TemperatureSetpoint1'

    @property
    def color_service(self):
        """Vera service string for color."""
        return 'urn:micasaverde-com:serviceId:Color1'

    def vera_request(self, **kwargs):
        """Perfom a vera_request for this device."""
        request_payload = {
            'output_format': 'json',
            'DeviceNum': self.device_id,
        }
        request_payload.update(kwargs)

        return self.vera_controller.data_request(request_payload)

    def set_service_value(self, service_id, set_name, parameter_name, value):
        """Set a variable on the vera device.

        This will call the Vera api to change device state.
        """
        payload = {
            'id': 'lu_action',
            'action': 'Set' + set_name,
            'serviceId': service_id,
            parameter_name: value
        }
        result = self.vera_request(**payload)
        logger.debug("set_service_value: "
                  "result of vera_request with payload %s: %s",
                  payload, result.text)

    def call_service(self, service_id, action):
        """Call a Vera service.

        This will call the Vera api to change device state.
        """
        result = self.vera_request(id='action', serviceId=service_id,
                                   action=action)
        logger.debug("call_service: "
                  "result of vera_request with id %s: %s", service_id,
                  result.text)
        return result

    def set_cache_value(self, name, value):
        """Set a variable in the local state dictionary.

        This does not change the physical device. Useful if you want the
        device state to refect a new value which has not yet updated drom
        Vera.
        """
        dev_info = self.json_state.get('deviceInfo')
        if dev_info.get(name.lower()) is None:
            logger.error("Could not set %s for %s (key does not exist).",
                      name, self.name)
            logger.error("- dictionary %s", dev_info)
            return
        dev_info[name.lower()] = str(value)

    def set_cache_complex_value(self, name, value):
        """Set a variable in the local complex state dictionary.

        This does not change the physical device. Useful if you want the
        device state to refect a new value which has not yet updated from
        Vera.
        """
        for item in self.json_state.get('states'):
            if item.get('variable') == name:
                item['value'] = str(value)

    def get_complex_value(self, name):
        """Get a value from the service dictionaries.

        It's best to use get_value if it has the data you require since
        the vera subscription only updates data in dev_info.
        """
        for item in self.json_state.get('states'):
            if item.get('variable') == name:
                return item.get('value')
        return None

    def get_all_values(self):
        """Get all values from the deviceInfo area.

        The deviceInfo data is updated by the subscription service.
        """
        return self.json_state.get('deviceInfo')

    def get_value(self, name):
        """Get a value from the dev_info area.

        This is the common Vera data and is the best place to get state from
        if it has the data you require.

        This data is updated by the subscription service.
        """
        return self.get_strict_value(name.lower())

    def get_strict_value(self, name):
        """Get a case-sensitive keys value from the dev_info area.
        """
        dev_info = self.json_state.get('deviceInfo')
        return dev_info.get(name, None)

    def refresh_complex_value(self, name):
        """Refresh a value from the service dictionaries.

        It's best to use get_value / refresh if it has the data you need.
        """
        for item in self.json_state.get('states'):
            if item.get('variable') == name:
                service_id = item.get('service')
                result = self.vera_request(**{
                    'id': 'variableget',
                    'output_format': 'json',
                    'DeviceNum': self.device_id,
                    'serviceId': service_id,
                    'Variable': name
                })
                item['value'] = result.text
                return item.get('value')
        return None

    def refresh(self):
        """Refresh the dev_info data used by get_value.

        Only needed if you're not using subscriptions.
        """
        j = self.vera_request(id='sdata', output_format='json').json()
        devices = j.get('devices')
        for device_data in devices:
            if device_data.get('id') == self.device_id:
                self.update(device_data)

    def update(self, params):
        """Update the dev_info data from a dictionary.

        Only updates if it already exists in the device.
        """
        dev_info = self.json_state.get('deviceInfo')
        dev_info.update({k: params[k] for k in params if dev_info.get(k)})

    @property
    def is_armable(self):
        """Device is armable."""
        return self.get_value('Armed') is not None

    @property
    def is_armed(self):
        """Device is armed now."""
        return self.get_value('Armed') == '1'

    @property
    def is_dimmable(self):
        """Device is dimmable."""
        return self.category == CATEGORY_DIMMER

    @property
    def is_trippable(self):
        """Device is trippable."""
        return self.get_value('Tripped') is not None

    @property
    def is_tripped(self):
        """Device is tripped now."""
        return self.get_value('Tripped') == '1'

    @property
    def has_battery(self):
        """Device has a battery."""
        return self.get_value('BatteryLevel') is not None

    @property
    def battery_level(self):
        """Battery level as a percentage."""
        return self.get_value('BatteryLevel')

    @property
    def last_trip(self):
        """Time device last tripped."""
        # Vera seems not to update this for my device!
        return self.get_value('LastTrip')

    @property
    def light(self):
        """Light level in lux."""
        return self.get_value('Light')

    @property
    def level(self):
        """Get level from vera."""
        # Used for dimmers, curtains
        # Have seen formats of 10, 0.0 and "0%"!
        level = self.get_value('level')
        try:
            return int(float(level))
        except (TypeError, ValueError):
            pass
        try:
            return int(level.strip('%'))
        except (TypeError, AttributeError, ValueError):
            pass
        return 0

    @property
    def temperature(self):
        """Temperature.

        You can get units from the controller.
        """
        return self.get_value('Temperature')

    @property
    def humidity(self):
        """Humidity level in percent."""
        return self.get_value('Humidity')

    @property
    def power(self):
        """Current power useage in watts"""
        return self.get_value('Watts')

    @property
    def energy(self):
        """Energy usage in kwh"""
        return self.get_value('kwh')

    @property
    def room_id(self):
        """Vera Room ID"""
        return self.get_value('room')

    @property
    def comm_failure(self):
        """Communication Failure Flag"""
        return self.get_strict_value('commFailure') != '0'

    @property
    def vera_device_id(self):
        """The ID Vera uses to refer to the device."""
        return self.device_id

    @property
    def should_poll(self):
        """Whether polling is needed if using subscriptions for this device."""
        return False


class VeraSwitch(VeraDevice):
    """Class to add switch functionality."""

    def set_switch_state(self, state):
        """Set the switch state, also update local state."""
        self.set_service_value(
            self.switch_service,
            'Target',
            'newTargetValue',
            state)
        self.set_cache_value('Status', state)

    def switch_on(self):
        """Turn the switch on, also update local state."""
        self.set_switch_state(1)

    def switch_off(self):
        """Turn the switch off, also update local state."""
        self.set_switch_state(0)

    def is_switched_on(self, refresh=False):
        """Get switch state.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        Refresh is only needed if you're not using subscriptions.
        """
        if refresh:
            self.refresh()
        val = self.get_value('Status')
        return val == '1'


class VeraDimmer(VeraSwitch):
    """Class to add dimmer functionality."""

    def switch_on(self):
        """Turn the dimmer on."""
        self.set_brightness(254)

    def switch_off(self):
        """Turn the dimmer off."""
        self.set_brightness(0)

    def is_switched_on(self, refresh=False):
        """Get dimmer state.

        Refresh data from Vera if refresh is True,
        otherwise use local cache. Refresh is only needed if you're
        not using subscriptions.
        """
        if refresh:
            self.refresh()
        return self.get_brightness(refresh) > 0

    def get_brightness(self, refresh=False):
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

    def set_brightness(self, brightness):
        """Set dimmer brightness.

        Converts the Vera level property for dimmable lights from a percentage
        to the 0 - 255 scale used by HA.
        """
        percent = 0
        if brightness > 0:
            percent = round(brightness / 2.55)

        self.set_service_value(
            self.dimmer_service,
            'LoadLevelTarget',
            'newLoadlevelTarget',
            percent)
        self.set_cache_value('level', percent)

    def get_color_index(self, colors, refresh=False):
        """Get color index.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        """
        if refresh:
            self.refresh_complex_value('SupportedColors')

        sup = self.get_complex_value('SupportedColors')
        if sup is None:
            return None

        sup = sup.split(',')
        if not set(colors).issubset(sup):
            return None

        return [sup.index(c) for c in colors]

    def get_color(self, refresh=False):
        """Get color.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        """
        if refresh:
            self.refresh_complex_value('CurrentColor')

        ci = self.get_color_index(['R', 'G', 'B'], refresh)
        cur = self.get_complex_value('CurrentColor')
        if ci is None or cur is None:
            return None

        try:
            val = [cur.split(',')[c] for c in ci]
            return [int(v.split('=')[1]) for v in val]
        except IndexError:
            return None

    def set_color(self, rgb):
        """Set dimmer color.
        """

        target = ','.join([str(c) for c in rgb])
        self.set_service_value(
            self.color_service,
            'ColorRGB',
            'newColorRGBTarget',
            target)

        rgbi = self.get_color_index(['R', 'G', 'B'])
        if rgbi is None:
            return

        target = ('0=0,1=0,' +
                  str(rgbi[0]) + '=' + str(rgb[0]) + ',' +
                  str(rgbi[1]) + '=' + str(rgb[1]) + ',' +
                  str(rgbi[2]) + '=' + str(rgb[2]))
        self.set_cache_complex_value("CurrentColor", target)


class VeraArmableDevice(VeraSwitch):
    """Class to represent a device that can be armed."""

    def set_armed_state(self, state):
        """Set the armed state, also update local state."""
        self.set_service_value(
            self.security_sensor_service,
            'Armed',
            'newArmedValue',
            state)
        self.set_cache_value('Armed', state)

    def switch_on(self):
        """Arm the device."""
        self.set_armed_state(1)

    def switch_off(self):
        """Disarm the device."""
        self.set_armed_state(0)

    def is_switched_on(self, refresh=False):
        """Get armed state.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        Refresh is only needed if you're not using subscriptions.
        """
        if refresh:
            self.refresh()
        val = self.get_value('Armed')
        return val == '1'


class VeraSensor(VeraDevice):
    """Class to represent a supported sensor."""


class VeraBinarySensor(VeraDevice):
    """Class to represent an on / off sensor."""

    def is_switched_on(self, refresh=False):
        """Get sensor on off state.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        Refresh is only needed if you're not using subscriptions.
        """
        if refresh:
            self.refresh()
        val = self.get_value('Status')
        return val == '1'


class VeraCurtain(VeraSwitch):
    """Class to add curtains functionality."""

    def open(self):
        """Open the curtains."""
        self.set_level(100)

    def close(self):
        """Close the curtains."""
        self.set_level(0)

    def stop(self):
        """Open the curtains."""
        self.call_service(
            self.window_covering_service,
            'Stop')
        return self.get_level(True)

    def is_open(self, refresh=False):
        """Get curtains state.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        Refresh is only needed if you're not using subscriptions.
        """
        if refresh:
            self.refresh()
        return self.get_level(refresh) > 0

    def get_level(self, refresh=False):
        """Get open level of the curtains.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        Refresh is only needed if you're not using subscriptions.
        Scale is 0-100
        """
        if refresh:
            self.refresh()
        return self.level

    def set_level(self, level):
        """Set open level of the curtains.

        Scale is 0-100
        """
        self.set_service_value(
            self.dimmer_service,
            'LoadLevelTarget',
            'newLoadlevelTarget',
            level)

        self.set_cache_value('level', level)


class VeraLock(VeraDevice):
    """Class to represent a door lock."""

    def set_lock_state(self, state):
        """Set the lock state, also update local state."""
        self.set_service_value(
            self.lock_service,
            'Target',
            'newTargetValue',
            state)

    def lock(self):
        """Lock the door."""
        self.set_lock_state(1)

    def unlock(self):
        """Unlock the device."""
        self.set_lock_state(0)

    def is_locked(self, refresh=False):
        """Get locked state.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        Refresh is only needed if you're not using subscriptions.
        Lock state can also be found with self.get_complex_value('Status')
        """
        if refresh:
            self.refresh()
        return self.get_value("locked") == '1'

    def get_last_user(self, refresh=False):
        """Get the last used PIN user id"""
        if refresh:
            self.refresh_complex_value('sl_UserCode')
        val = self.get_complex_value("sl_UserCode")
        # Syntax string: UserID="<pin_slot>" UserName="<pin_code_name>"
        # See http://wiki.micasaverde.com/index.php/Luup_UPnP_Variables_and_Actions#DoorLock1

        try:
            # Get the UserID="" and UserName="" fields separately
            raw_userid, raw_username = val.split(' ')
            # Get the right hand value without quotes of UserID="<here>"
            userid = raw_userid.split('=')[1].split('"')[1]
            # Get the right hand value without quotes of UserName="<here>"
            username = raw_username.split('=')[1].split('"')[1]
        except Exception as ex:
            logger.error('Got unsupported user string {}: {}'.format(val, ex))
            return None

        return ( userid, username )

    def get_pin_failed(self, refresh=False):
        """True when a bad PIN code was entered"""
        if refresh:
            self.refresh_complex_value('sl_PinFailed')
        return self.get_complex_value("sl_PinFailed") == '1'

    def get_unauth_user(self, refresh=False):
        """True when a user code entered was outside of a valid date"""
        if refresh:
            self.refresh_complex_value('sl_UnauthUser')
        return self.get_complex_value("sl_UnauthUser") == '1'

    def get_lock_failed(self, refresh=False):
        """True when the lock fails to operate"""
        if refresh:
            self.refresh_complex_value('sl_LockFailure')
        return self.get_complex_value("sl_LockFailure") == '1'

    def get_pin_codes(self, refresh=False):
        """Get the list of PIN codes

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
        raw_code_list = []
        try:
            raw_code_list = val.rstrip().split('\t')[1:]
        except Exception as ex:
            logger.error('Got unsupported string {}: {}'.format(val, ex))

        # Loop to create a list of codes
        codes = []
        for code in raw_code_list:

            try:
                # Strip off trailing semicolon
                # Create a list from csv
                code_addrs = code.split(';')[0].split(',')

                # Get the code ID (slot) and see if it should have values
                slot, active = code_addrs[:2]
                if active != '0':
                    # Since it has additional attributes, get the remaining ones
                    _, _, pin, name = code_addrs[2:]
                    # And add them as a tuple to the list
                    codes.append((slot, name, pin))
            except Exception as ex:
                logger.error('Problem parsing pin code string {}: {}'.format(code, ex))
        
        return codes

    @property
    def should_poll(self):
        return True


class VeraThermostat(VeraDevice):
    """Class to represent a thermostat."""

    def set_temperature(self, temp):
        """Set current goal temperature / setpoint"""

        self.set_service_value(
            self.thermostat_setpoint,
            'CurrentSetpoint',
            'NewCurrentSetpoint',
            temp)

        self.set_cache_value('setpoint', temp)

    def get_current_goal_temperature(self, refresh=False):
        """Get current goal temperature / setpoint"""
        if refresh:
            self.refresh()
        try:
            return float(self.get_value('setpoint'))
        except (TypeError, ValueError):
            return None

    def get_current_temperature(self, refresh=False):
        """Get current temperature"""
        if refresh:
            self.refresh()
        try:
            return float(self.get_value('temperature'))
        except (TypeError, ValueError):
            return None

    def set_hvac_mode(self, mode):
        """Set the hvac mode"""
        self.set_service_value(
            self.thermostat_operating_service,
            'ModeTarget',
            'NewModeTarget',
            mode)
        self.set_cache_value('mode', mode)

    def get_hvac_mode(self, refresh=False):
        """Get the hvac mode"""
        if refresh:
            self.refresh()
        return self.get_value("mode")

    def turn_off(self):
        """Set hvac mode to off"""
        self.set_hvac_mode('Off')

    def turn_cool_on(self):
        """Set hvac mode to cool"""
        self.set_hvac_mode('CoolOn')

    def turn_heat_on(self):
        """Set hvac mode to heat"""
        self.set_hvac_mode('HeatOn')

    def turn_auto_on(self):
        """Set hvac mode to auto"""
        self.set_hvac_mode('AutoChangeOver')

    def set_fan_mode(self, mode):
        """Set the fan mode"""
        self.set_service_value(
            self.thermostat_fan_service,
            'Mode',
            'NewMode',
            mode)
        self.set_cache_value('fanmode', mode)

    def fan_on(self):
        """Turn fan on"""
        self.set_fan_mode('ContinuousOn')

    def fan_off(self):
        """Turn fan off"""
        self.set_fan_mode('Off')

    def get_fan_mode(self, refresh=False):
        """Get fan mode"""
        if refresh:
            self.refresh()
        return self.get_value("fanmode")

    def get_hvac_state(self, refresh=False):
        """Get current hvac state"""
        if refresh:
            self.refresh()
        return self.get_value("hvacstate")

    def fan_auto(self):
        """Set fan to automatic"""
        self.set_fan_mode('Auto')

    def fan_cycle(self):
        """Set fan to cycle"""
        self.set_fan_mode('PeriodicOn')


class VeraSceneController(VeraDevice):
    """Class to represent a scene controller."""

    def get_last_scene_id(self, refresh=False):
        """Get last scene id.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        Refresh is only needed if you're not using subscriptions.
        """
        if refresh:
            self.refresh_complex_value('LastSceneID')
            self.refresh_complex_value('sl_CentralScene')
        val = self.get_complex_value('LastSceneID') or self.get_complex_value('sl_CentralScene')
        return val

    def get_last_scene_time(self, refresh=False):
        """Get last scene time.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        Refresh is only needed if you're not using subscriptions.
        """
        if refresh:
            self.refresh_complex_value('LastSceneTime')
        val = self.get_complex_value('LastSceneTime')
        return val

    @property
    def should_poll(self):
        return True


class VeraScene(object):
    """Class to represent a scene that can be activated.

    This does not inherit from a VeraDevice since scene ids
    and device ids are separate sets.  A scene is not a device
    as far as Vera is concerned.

    TODO: The duplicated code between VeraScene & VeraDevice should
    be refactored at some point to be reused.  Perhaps a VeraObject?
    """

    def __init__(self, json_obj, vera_controller):
        """Setup a Vera scene."""
        self.json_state = json_obj
        self.scene_id = self.json_state.get('id')
        self.vera_controller = vera_controller
        self.name = self.json_state.get('name')
        self._active = False

        if not self.name:
            self.name = ('Vera Scene ' + self.name +
                         ' ' + str(self.scene_id))

    def __repr__(self):
        if sys.version_info >= (3, 0):
            return "{} (id={} name={})".format(
                self.__class__.__name__,
                self.scene_id,
                self.name)
        else:
            return u"{} (id={} name={})".format(
                self.__class__.__name__,
                self.scene_id,
                self.name).encode('utf-8')

    @property
    def scene_service(self):
        """Vera service string for switch."""
        return 'urn:micasaverde-com:serviceId:HomeAutomationGateway1'

    def vera_request(self, **kwargs):
        """Perfom a vera_request for this scene."""
        request_payload = {
            'output_format': 'json',
            'SceneNum': self.scene_id,
        }
        request_payload.update(kwargs)

        return self.vera_controller.data_request(request_payload)

    def activate(self):
        """Activate a Vera scene.

        This will call the Vera api to activate a scene.
        """
        payload = {
            'id': 'lu_action',
            'action': 'RunScene',
            'serviceId': self.scene_service
        }
        result = self.vera_request(**payload)
        logger.debug("activate: "
                  "result of vera_request with payload %s: %s",
                  payload, result.text)

        self._active = True

    def update(self, params):
        self._active = params['active'] == 1

    def refresh(self):
        """Refresh the data used by get_value.

        Only needed if you're not using subscriptions.
        """
        j = self.vera_request(id='sdata', output_format='json').json()
        scenes = j.get('scenes')
        for scene_data in scenes:
            if scene_data.get('id') == self.scene_id:
                self.update(scene_data)

    @property
    def is_active(self):
        """Is Scene active."""
        return self._active

    @property
    def vera_scene_id(self):
        """The ID Vera uses to refer to the scene."""
        return self.scene_id

    @property
    def should_poll(self):
        """Whether polling is needed if using subscriptions for this device."""
        return True
