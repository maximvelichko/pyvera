import requests

from .subscribe import SubscriptionRegistry

__author__ = 'jamespcole'

"""
Vera Controller Python API
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This lib is designed to simplify communication with Vera controllers
"""
# Time to block on Vera poll if there are no changes in seconds
SUBSCRIPTION_WAIT = 30
# Min time to wait for event in miliseconds
SUBSCRIPTION_MIN_WAIT = 200


_VERA_CONTROLLER = None


def init_controller(url):
    global _VERA_CONTROLLER
    created = False
    if _VERA_CONTROLLER is None:
        _VERA_CONTROLLER = VeraController(url)
        created = True
        _VERA_CONTROLLER.start()
    return [_VERA_CONTROLLER, created]


def get_controller():
    return _VERA_CONTROLLER


class VeraController(object):

    temperature_units = 'C'

    def __init__(self, base_url):
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

    # get list of connected devices, the category_filter param can be either
    # a string or array of strings
    def get_devices(self, category_filter=''):

        # the Vera rest API is a bit rough so we need to make 2 calls to get
        # all the info e need
        self.get_simple_devices_info()

        arequest_url = (self.base_url
                        + "/data_request?id=status&output_format=json")
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
            else:
                self.devices.append(VeraDevice(item, self))

        if category_filter == '':
            return self.devices
        else:
            filter_categories = []
            if isinstance(category_filter, str):
                filter_categories.append(category_filter)
            else:
                filter_categories = category_filter

            devices = []
            for item in self.devices:
                if item.category in filter_categories:
                    devices.append(item)
            return devices

    def refresh_data(self):
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

        # the Vera rest API is a bit rough so we need to make 2 calls
        # to get all the info e need
        self.get_simple_devices_info()

        arequest_url = (self.base_url
                        + "/data_request?id=status&output_format=json")
        j = requests.get(arequest_url).json()

        service_map = {}

        items = j.get('devices')

        for item in items:
            service_map[item.get('id')] = item.get('states')

        self.device_services_map = service_map

    def get_changed_devices(self, timestamp):
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
        self.subscription_registry.start()

    def stop(self):
        self.subscription_registry.stop()

    def register(self, device, callback):
        self.subscription_registry.register(device, callback)


class VeraDevice(object):

    def __init__(self, json_obj, vera_controller):
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

    def get_value(self, name):
        for item in self.json_state.get('states'):
            if item.get('variable') == name:
                return item.get('value')
        return None

    def refresh_value(self, name):
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

    def update(self, params):
        for key in params:
            for item in self.json_state.get('states'):
                if item.get('variable').lower() == key.lower():
                    item['value'] = params[key]

    @property
    def is_armable(self):
        return self.get_value('Armed') is not None

    @property
    def is_dimmable(self):
        return self.category == "Dimmable Switch"

    @property
    def is_trippable(self):
        return self.get_value('Tripped') is not None

    @property
    def has_battery(self):
        return self.get_value('BatteryLevel') is not None

    @property
    def battery_level(self):
        return self.refresh_value('BatteryLevel')

    @property
    def vera_device_id(self):
        return self.device_id


class VeraSwitch(VeraDevice):

    def __init__(self, json_obj, vera_controller):
        super().__init__(json_obj, vera_controller)

    def switch_on(self):
        self.set_value('Target', 1)

    def switch_off(self):
        self.set_value('Target', 0)

    def is_switched_on(self, refresh=False):
        if refresh:
            self.refresh_value('Status')
        val = self.get_value('Status')
        return val == '1'


class VeraDimmer(VeraSwitch):

    def __init__(self, json_obj, vera_controller):
        super().__init__(json_obj, vera_controller)
        self.brightness = None

    def switch_on(self):
        self.set_brightness(self.brightness or 254)

    def switch_off(self):
        self.brightness = 0
        self.set_brightness(self.brightness)

    def is_switched_on(self, refresh=False):
        return self.get_brightness(refresh) > 0

    def get_brightness(self, refresh=False):
        """ Converts the Vera level property for dimmable lights from a
        percentage to the 0 - 255 scale used by HA """
        if self.brightness is not None and not refresh:
            return self.brightness
        percent = int(self.refresh_value('LoadLevelStatus'))
        self.brightness = 0
        if percent > 0:
            self.brightness = round(percent * 2.55)
        return int(self.brightness)

    def set_brightness(self, brightness):
        """ Converts the Vera level property for dimmable lights from a
        percentage to the 0 - 255 scale used by HA """
        percent = 0
        if brightness > 0:
            percent = round(brightness / 2.55)
        self.brightness = brightness
        self.set_value('LoadLevelTarget', percent)


class VeraArmableDevice(VeraSwitch):

    def __init__(self, json_obj, vera_controller):
        super().__init__(json_obj, vera_controller)

    def switch_on(self):
        self.set_value('Armed', 1)

    def switch_off(self):
        self.set_value('Armed', 0)

    def is_switched_on(self, refresh=False):
        if refresh:
            self.refresh_value('Armed')
        val = self.get_value('Armed')
        return val == '1'


class VeraSensor(VeraDevice):

    def __init__(self, json_obj, vera_controller):
        super().__init__(json_obj, vera_controller)

    def switch_on(self):
        self.set_value('Target', 1)

    def switch_off(self):
        self.set_value('Target', 0)

    def is_switched_on(self):
        self.refresh_value('Status')
        val = self.get_value('Status')
        return val == '1'
