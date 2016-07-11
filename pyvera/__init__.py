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

    def get_simple_devices_info(self):
        """Get basic device info from Vera."""
        simple_request_url = self.base_url + "/data_request?id=sdata"
        j = requests.get(simple_request_url).json()

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

        arequest_url = (self.base_url +
                        "/data_request?id=status&output_format=json")
        j = requests.get(arequest_url).json()

        self.devices = []
        items = j.get('devices')

        for item in items:
            item['deviceInfo'] = self.device_id_map.get(item.get('id'))
            if (item.get('deviceInfo') and
                    item.get('deviceInfo').get('categoryName') ==
                    'Switch'):
                self.devices.append(VeraSwitch(item, self))
            elif (item.get('deviceInfo') and
                  item.get('deviceInfo').get('categoryName') ==
                  'On/Off Switch'):
                self.devices.append(VeraSwitch(item, self))
            elif (item.get('deviceInfo') and
                  item.get('deviceInfo').get('categoryName') ==
                  'Dimmable Switch'):
                self.devices.append(VeraDimmer(item, self))
            elif (item.get('deviceInfo') and
                  item.get('deviceInfo').get('categoryName') ==
                  'Dimmable Light'):        
                dimmer = VeraDimmer(item, self)
                dimmer.category = "Dimmable Switch"
                self.devices.append(dimmer)
            elif (item.get('deviceInfo') and
                  item.get('deviceInfo').get('categoryName') ==
                  'Temperature Sensor'):
                self.devices.append(VeraSensor(item, self))
            elif (item.get('deviceInfo') and
                  item.get('deviceInfo').get('categoryName') ==
                  'Sensor'):
                sensor = VeraSensor(item, self)
                self.devices.append(sensor)
                if sensor.is_armable:
                    armable = VeraArmableDevice(item, self)
                    armable.category = 'Armable Sensor'
                    self.devices.append(armable)
            elif (item.get('deviceInfo') and
                  item.get('deviceInfo').get('categoryName') ==
                  'Light Sensor'):
                self.devices.append(VeraSensor(item, self))
            elif (item.get('deviceInfo') and
                  item.get('deviceInfo').get('categoryName') ==
                  'Window Covering'):
                self.devices.append(VeraCurtain(item, self))
            elif (item.get('deviceInfo') and
                  item.get('deviceInfo').get('categoryName') ==
                  'Doorlock'):
                self.devices.append(VeraLock(item, self))
            elif (item.get('deviceInfo') and
                  item.get('deviceInfo').get('categoryName') ==
                  'Door lock'):
                doorlock = VeraLock(item, self)
                doorlock.category = 'Doorlock'
                self.devices.append(doorlock)
            else:
                self.devices.append(VeraDevice(item, self))

        if not category_filter:
            return self.devices
        else:
            devices = []
            for device in self.devices:
                if (device.category is not None and device.category != '' and
                        device.category in category_filter):
                    devices.append(device)
            return devices

    def refresh_data(self):
        """Refresh data from Vera device."""
        simple_request_url = self.base_url + "/data_request?id=sdata"
        j = requests.get(simple_request_url).json()

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

        arequest_url = (self.base_url +
                        "/data_request?id=status&output_format=json")
        j = requests.get(arequest_url).json()

        service_map = {}

        items = j.get('devices')

        for item in items:
            service_map[item.get('id')] = item.get('states')

        self.device_services_map = service_map

    def get_changed_devices(self, timestamp):
        """Get data since last timestamp.

        This is done via a blocking call, pass NONE for initial state.
        """
        simple_request_url = self.base_url + "/data_request?id=lu_sdata"
        if timestamp is None:
            payload = {}
        else:
            payload = {
                'timeout': SUBSCRIPTION_WAIT,
                'minimumdelay': SUBSCRIPTION_MIN_WAIT
            }
            payload.update(timestamp)
        result = requests.get(simple_request_url, params=payload).json()
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


class VeraDevice(object):
    """Class to represent each vera device."""

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

    def set_value(self, name, value):
        """Set a variable on the vera device.

        This will call the Vera api to change device state.
        """
        for item in self.json_state.get('states'):
            if item.get('variable') == name:
                service_name = item.get('service')
                # The Vera API is very inconsistent so we can't be very
                # generic here unfortunately
                if name == 'LoadLevelTarget':
                    # note the incredibly lame change to the
                    # last payload parameter
                    payload = {
                        'id': 'lu_action',
                        'output_format': 'json',
                        'DeviceNum': self.device_id,
                        'serviceId': service_name,
                        'action': 'Set' + name,
                        'newLoadlevelTarget': value}
                else:
                    payload = {
                        'id': 'lu_action',
                        'output_format': 'json',
                        'DeviceNum': self.device_id,
                        'serviceId': service_name,
                        'action': 'Set' + name,
                        'new' + name + 'Value': value}
                request_url = self.vera_controller.base_url + "/data_request"
                requests.get(request_url, params=payload)
                item['value'] = value

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
                service_name = item.get('service')
                payload = {
                    'id': 'variableget',
                    'output_format': 'json',
                    'DeviceNum': self.device_id,
                    'serviceId': service_name,
                    'Variable': name}
                request_url = self.vera_controller.base_url + "/data_request"
                result = requests.get(request_url, params=payload)
                item['value'] = result.text
                return item.get('value')
        return None

    def refresh(self):
        """Refresh the dev_info data used by get_value.

        Only needed if you're not using subscriptions.
        """
        arequest_url = (self.vera_controller.base_url +
                        "/data_request?id=sdata&output_format=json")
        j = requests.get(arequest_url).json()
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
    def vera_device_id(self):
        """The ID Vera uses to refer to the device."""
        return self.device_id


class VeraSwitch(VeraDevice):
    """Class to add switch functionality."""

    def switch_on(self):
        """Turn the switch on, also update local state."""
        self.set_value('Target', 1)
        self.set_cache_value('Status', 1)

    def switch_off(self):
        """Turn the switch off, also update local state."""
        self.set_value('Target', 0)
        self.set_cache_value('Status', 0)

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
        level = self.get_value('level')
        percent = 0 if level is None else int(level)
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
        self.set_value('LoadLevelTarget', percent)
        self.set_cache_value('level', percent)


class VeraArmableDevice(VeraSwitch):
    """Class to represent a device that can be armed."""

    def switch_on(self):
        """Arm the device."""
        self.set_value('Armed', 1)
        self.set_cache_value('Armed', 1)

    def switch_off(self):
        """Disarm the device."""
        self.set_value('Armed', 0)
        self.set_cache_value('Armed', 0)

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
    """Class to represent a sensor."""

    def switch_on(self):
        """Turn the sensor on."""
        self.set_value('Target', 1)
        self.set_cache_value('Status', 1)

    def switch_off(self):
        """Turn the sensor off."""
        self.set_value('Target', 0)
        self.set_cache_value('Status', 0)

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
        self.set_level(254)

    def close(self):
        """Close the curtains."""
        self.set_level(0)

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
        Converts the Vera level property for curtains from a percentage to the
        0 - 255 scale used by HA.
        """
        if refresh:
            self.refresh()
        value = 0
        level = self.get_value('level')
        percent = 0 if level is None else int(level)
        if percent > 0:
            value = round(percent * 2.55)
        return int(value)

    def set_level(self, level):
        """Set open level of the curtains.

        Converts the Vera level property for curtains from a percentage to the
        0 - 255 scale used by HA.
        """
        percent = 0
        if level > 0:
            percent = round(level / 2.55)
        self.set_value('LoadLevelTarget', percent)
        self.set_cache_value('level', percent)


class VeraLock(VeraDevice):
    """Class to represent a door lock."""

    def lock(self):
        """Lock the door."""
        self.set_value('Target', 1)

    def unlock(self):
        """Unlock the device."""
        self.set_value('Target', 0)

    def is_locked(self, refresh=False):
        """Get locked state.

        Refresh data from Vera if refresh is True, otherwise use local cache.
        Refresh is only needed if you're not using subscriptions.
        """
        if refresh:
            self.refresh_complex_value('Status')
        val = self.get_complex_value('Status')
        return val == '1'
