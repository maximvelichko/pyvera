import json
import time

import requests

from .subscribe import SubscriptionRegistry

__author__ = 'jamespcole'

"""
Vera Controller Python API
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This lib is designed to simplify communication with Vera Z-Wave controllers
"""

SUBSCRIPTION_WAIT = 60
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

    def __init__(self, baseUrl):
        self.BASE_URL = baseUrl
        self.devices = []
        self.temperature_units = 'C'
        self.version = None
        self.model = None
        self.serial_number = None
        self.device_services_map = None
        self.subscription_registry = SubscriptionRegistry()

    def get_simple_devices_info(self):

        simpleRequestUrl = self.BASE_URL + "/data_request?id=sdata"
        j = requests.get(simpleRequestUrl).json()

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

    #get list of connected devices, the categoryFilter param can be either a string or array of strings
    def get_devices(self, categoryFilter=''):

        # the Vera rest API is a bit rough so we need to make 2 calls to get all the info e need
        self.get_simple_devices_info()

        arequestUrl = self.BASE_URL + "/data_request?id=status&output_format=json"
        j = requests.get(arequestUrl).json()

        self.devices = []
        items = j.get('devices')

        for item in items:
            item['deviceInfo'] = self.device_id_map.get(item.get('id'))
            if item.get('deviceInfo') and item.get('deviceInfo').get('categoryName') == 'Switch':
                self.devices.append(VeraSwitch(item, self))
            elif item.get('deviceInfo') and item.get('deviceInfo').get('categoryName') == 'On/Off Switch':
                self.devices.append(VeraSwitch(item, self))
            elif item.get('deviceInfo') and item.get('deviceInfo').get('categoryName') == 'Dimmable Switch':
                self.devices.append(VeraDimmer(item, self))
            elif item.get('deviceInfo') and item.get('deviceInfo').get('categoryName') == 'Temperature Sensor':
                self.devices.append(VeraSensor(item, self))
            elif item.get('deviceInfo') and item.get('deviceInfo').get('categoryName') == 'Sensor':
                sensor = VeraSensor(item, self)
                self.devices.append(sensor)
                if sensor.is_armable:
                    armable = VeraArmableDevice(item, self)
                    armable.category = 'Armable Sensor'
                    self.devices.append(armable)
            elif item.get('deviceInfo') and item.get('deviceInfo').get('categoryName') == 'Light Sensor':
                self.devices.append(VeraSensor(item, self))
            else:
                self.devices.append(VeraDevice(item, self))

        if categoryFilter == '':
            return self.devices
        else:
            filterCategories = []
            if isinstance(categoryFilter, str):
                filterCategories.append(categoryFilter)
            else:
                filterCategories = categoryFilter

            devices = []
            for item in self.devices:
                if item.category in filterCategories:
                    devices.append(item)
            return devices

    def refresh_data(self):
        simpleRequestUrl = self.BASE_URL + "/data_request?id=sdata"
        j = requests.get(simpleRequestUrl).json()

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

        # the Vera rest API is a bit rough so we need to make 2 calls to get all the info e need
        self.get_simple_devices_info()

        arequestUrl = self.BASE_URL + "/data_request?id=status&output_format=json"
        j = requests.get(arequestUrl).json()

        service_map = {}

        items = j.get('devices')

        for item in items:
            service_map[item.get('id')] = item.get('states')

        self.device_services_map = service_map

    def set_value(self, device_id, name, value):
        if self.device_services_map is None:
            self.map_services()

        if device_id not in self.device_services_map.keys():
            return

        states = self.device_services_map.get(device_id)

        for item in states:
            if item.get('variable') == name:
                serviceName = item.get('service')

                # The Vera API is very inconsistent so we can't be very generic here unfortunately
                if name == 'LoadLevelTarget':
                    # note the incredibly lame change to the last payload parameter
                    payload = {'id': 'lu_action', 'output_format': 'json', 'DeviceNum': device_id, 'serviceId': serviceName, 'action': 'Set' + name, 'newLoadlevelTarget': value}
                else:
                    payload = {'id': 'lu_action', 'output_format': 'json', 'DeviceNum': device_id, 'serviceId': serviceName, 'action': 'Set' + name, 'new' + name + 'Value': value}

                requestUrl = self.BASE_URL + "/data_request"
                r = requests.get(requestUrl, params=payload)

                break
                item['value'] = value

    def get_initial_timestamp(self):
        simpleRequestUrl = self.BASE_URL + "/data_request?id=lu_sdata"
        j = requests.get(simpleRequestUrl).json()
        timestamp = {
            'loadtime': j.get('loadtime'),
            'dataversion': j.get('dataversion')
        }
        return timestamp

    def get_changed_devices(self, timestamp):
        simpleRequestUrl = self.BASE_URL + "/data_request?id=lu_sdata"
        payload = {
            'timeout': SUBSCRIPTION_WAIT,
            'minimumdelay': SUBSCRIPTION_MIN_WAIT
        }
        payload.update(timestamp)
        j = requests.get(simpleRequestUrl, params=payload).json()
        device_ids = [dev['id'] for dev in j.get('devices')]
        timestamp = {
            'loadtime': j.get('loadtime'),
            'dataversion': j.get('dataversion')
        }
        return [device_ids, timestamp]

        self.categories = {}
        cats = j.get('categories')

        for cat in cats:
            self.categories[cat.get('id')] = cat.get('name')

        self.device_id_map = {}

        devs = j.get('devices')
        for dev in devs:
            dev['categoryName'] = self.categories.get(dev.get('category'))
            self.device_id_map[dev.get('id')] = dev


    def start(self):
        self.subscription_registry.start()

    def stop(self):
        self.subscription_registry.stop()

    def register(self, device):
        self.subscription_registry.register(device)

    def on(self, *params):
        self.subscription_registry.on(*params)

class VeraDevice(object):

    def __init__(self, aJSonObj, veraController):
        self.jsonState = aJSonObj
        self.deviceId = self.jsonState.get('id')
        self.veraController = veraController
        self.name = ''
        if self.jsonState.get('deviceInfo'):
            self.category = self.jsonState.get('deviceInfo').get('categoryName')
            self.name = self.jsonState.get('deviceInfo').get('name')
        else:
            self.category = ''

        if not self.name:
            if self.category:
                self.name = 'Vera ' + self.category + ' ' + str(self.deviceId)
            else:
                self.name = 'Vera Device ' + str(self.deviceId)


    def set_value(self, name, value):
        for item in self.jsonState.get('states'):
            if item.get('variable') == name:
                serviceName = item.get('service')
                # The Vera API is very inconsistent so we can't be very generic here unfortunately
                if name == 'LoadLevelTarget':
                    # note the incredibly lame change to the last payload parameter
                    payload = {'id': 'lu_action', 'output_format': 'json', 'DeviceNum': self.deviceId, 'serviceId': serviceName, 'action': 'Set' + name, 'newLoadlevelTarget': value}
                else:
                    payload = {'id': 'lu_action', 'output_format': 'json', 'DeviceNum': self.deviceId, 'serviceId': serviceName, 'action': 'Set' + name, 'new' + name + 'Value': value}
                requestUrl = self.veraController.BASE_URL + "/data_request"
                r = requests.get(requestUrl, params=payload)
                item['value'] = value

    def get_value(self, name):
        for item in self.jsonState.get('states'):
            if item.get('variable') == name:
                return item.get('value')
        return None

    def refresh_value(self, name):
        for item in self.jsonState.get('states'):
            if item.get('variable') == name:
                serviceName = item.get('service')
                payload = {'id': 'variableget', 'output_format': 'json', 'DeviceNum': self.deviceId, 'serviceId': serviceName, 'Variable': name}
                requestUrl = self.veraController.BASE_URL + "/data_request"
                r = requests.get(requestUrl, params=payload)
                item['value'] = r.text
                return item.get('value')
        return None

    @property
    def is_armable(self):
        if self.get_value('Armed') is not None:
            return True
        else:
            return False

    @property
    def is_dimmable(self):
        return self.category == "Dimmable Switch"

    @property
    def is_trippable(self):
        if self.get_value('Tripped') is not None:
            return True
        else:
            return False

    @property
    def has_battery(self):
        if self.get_value('BatteryLevel') is not None:
            return True
        else:
            return False

    @property
    def battery_level(self):
        return self.refresh_value('BatteryLevel')

    @property
    def vera_device_id(self):
        return self.deviceId


class VeraSwitch(VeraDevice):

    def __init__(self, aJSonObj, veraController):
        super().__init__(aJSonObj, veraController)

    def switch_on(self):
        self.set_value('Target', 1)

    def switch_off(self):
        self.set_value('Target', 0)

    def is_switched_on(self):
        self.refresh_value('Status')
        val = self.get_value('Status')
        if val == '1':
            return True
        else:
            return False

class VeraDimmer(VeraSwitch):

    def __init__(self, aJSonObj, veraController):
        super().__init__(aJSonObj, veraController)
        self.brightness = None

    def switch_on(self):
        self.set_brightness(self.brightness or 254)

    def switch_off(self):
        self.brightness = 0
        self.set_value('Target', 0)

    def is_switched_on(self):
        return self.get_brightness(True) > 0

    def get_brightness(self, refresh=False):
        """ Converts the Vera level property for dimmable lights from a
        percentage to the 0 - 255 scale used by HA """
        if self.brightness != None and not refresh:
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

    def __init__(self, aJSonObj, veraController):
        super().__init__(aJSonObj, veraController)

    def switch_on(self):
        self.set_value('Armed', 1)

    def switch_off(self):
        self.set_value('Armed', 0)

    def is_switched_on(self):
        self.refresh_value('Armed')
        val = self.get_value('Armed')
        if val == '1':
            return True
        else:
            return False


class VeraSensor(VeraDevice):

    def __init__(self, aJSonObj, veraController):
        super().__init__(aJSonObj, veraController)

    def switch_on(self):
        self.set_value('Target', 1)

    def switch_off(self):
        self.set_value('Target', 0)

    def is_switched_on(self):
        self.refresh_value('Status')
        val = self.get_value('Status')
        if val == '1':
            return True
        else:
            return False
