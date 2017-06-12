"""
Vera Controller Python API.

This lib is designed to simplify communication with Vera controllers
"""
import logging
import requests

from .subscribe import SubscriptionRegistry

__author__ = 'jamespcole'

# Time to block on Vera poll if there are no changes in seconds
SUBSCRIPTION_WAIT = 30
# Min time to wait for event in miliseconds
SUBSCRIPTION_MIN_WAIT = 200
# Timeout for requests calls, as vera sometimes just sits on sockets.
TIMEOUT = SUBSCRIPTION_WAIT


_VERA_CONTROLLER = None

LOG = logging.getLogger(__name__)


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
                device_category = item.get('deviceInfo').get('categoryName')
                if device_category == 'Switch':
                    self.devices.append(VeraSwitch(item, self))
                elif device_category == 'On/Off Switch':
                    self.devices.append(VeraSwitch(item, self))
                elif device_category == 'Dimmable Switch':
                    self.devices.append(VeraDimmer(item, self))
                elif device_category == 'Dimmable Light':
                    self.devices.append(VeraDimmer(item, self))
                elif device_category == 'Temperature Sensor':
                    self.devices.append(VeraSensor(item, self))
                elif device_category == 'Humidity Sensor':
                    self.devices.append(VeraSensor(item, self))
                elif device_category == 'Light Sensor':
                    self.devices.append(VeraSensor(item, self))
                elif device_category == 'Power meter':
                    self.devices.append(VeraSensor(item, self))
                elif device_category == 'Sensor':
                    sensor = VeraBinarySensor(item, self)
                    self.devices.append(sensor)
                    if sensor.is_armable:
                        armable = VeraArmableDevice(item, self)
                        armable.category = 'Armable Sensor'
                        self.devices.append(armable)
                elif device_category == 'Light Sensor':
                    self.devices.append(VeraSensor(item, self))
                elif device_category == 'Window Covering':
                    self.devices.append(VeraCurtain(item, self))
                elif device_category == 'Window covering':
                    self.devices.append(VeraCurtain(item, self))
                elif device_category == 'Doorlock':
                    self.devices.append(VeraLock(item, self))
                elif device_category == 'Door lock':
                    self.devices.append(VeraLock(item, self))
                elif device_category == 'Thermostat':
                    self.devices.append(VeraThermostat(item, self))
                elif device_category == 'Scene Controller':
                    self.devices.append(VeraSceneController(item, self))
            else:
                self.devices.append(VeraDevice(item, self))

        if not category_filter:
            return self.devices

        devices = []
        for device in self.devices:
            if (device.category is not None and device.category != '' and
                    device.category in category_filter):
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
        result = self.data_request(payload, TIMEOUT*2).json()
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


class VeraDevice(object):  # pylint: disable=R0904
    """ Class to represent each vera device."""

    def __init__(self, json_obj, vera_controller):
        """Setup a Vera device."""
        self.json_state = json_obj
        self.device_id = self.json_state.get('id')
        self.vera_controller = vera_controller
        self.name = ''

        if self.json_state.get('deviceInfo'):
            self.category = (
                self.json_state.get('deviceInfo').get('categoryName'))
            self.name = self.json_state.get('deviceInfo').get('name')
        else:
            self.category = ''

        if not self.name:
            if self.category:
                self.name = 'Vera ' + self.category + ' ' + str(self.device_id)
            else:
                self.name = 'Vera Device ' + str(self.device_id)

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
        LOG.debug("set_service_value: "
                  "result of vera_request with payload %s: %s",
                  payload, result.text)

    def call_service(self, service_id, action):
        """Call a Vera service.

        This will call the Vera api to change device state.
        """
        result = self.vera_request(id='action', serviceId=service_id,
                                   action=action)
        LOG.debug("call_service: "
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
            LOG.error("Could not set %s for %s (key does not exist).",
                      name, self.name)
            LOG.error("- dictionary %s", dev_info)
            return
        dev_info[name.lower()] = str(value)

    def set_cache_complex_value(self, name, value):
        """Set a variable in the local complex state dictionary.

        This does not change the physical device. Useful if you want the
        device state to refect a new value which has not yet updated drom
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

    def get_value(self, name):
        """Get a value from the dev_info area.

        This is the common Vera data and is the best place to get state from
        if it has the data you require.

        This data is updated by the subscription service.
        """
        dev_info = self.json_state.get('deviceInfo')
        return dev_info.get(name.lower(), None)

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
        return 'dimmable' in self.category.lower()

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
        """Energy useage in kwh"""
        return self.get_value('kwh')

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

        ci = None
        sup = self.get_complex_value('SupportedColors')
        if sup is not None:
            ci = [sup.split(',').index(c) for c in colors]
        return ci

    def get_color(self, refresh=False):
        """Get color.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        """
        if refresh:
            self.refresh_complex_value('CurrentColor')

        rgb = None
        ci = self.get_color_index(['R', 'G', 'B'], refresh)
        cur = self.get_complex_value('CurrentColor')
        if ci is not None and cur is not None:
            val = [cur.split(',')[c] for c in ci]
            rgb = [int(v.split('=')[1]) for v in val]
        return rgb

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
        """
        if refresh:
            self.refresh_complex_value('Status')
        val = self.get_complex_value('Status')
        return val == '1'

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
        return float(self.get_value('setpoint'))

    def get_current_temperature(self, refresh=False):
        """Get current temperature"""
        if refresh:
            self.refresh()
        return float(self.get_value('temperature'))

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
        val = self.get_complex_value('LastSceneID')
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
