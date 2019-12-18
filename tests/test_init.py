import logging
from typing import Any

import pyvera
from pyvera import (
    VeraBinarySensor,
    VeraDimmer,
    VeraLock,
    VeraSceneController,
    VeraSensor,
    VeraThermostat,
)

from .common import (
    DEVICE_ALARM_SENSOR_ID,
    DEVICE_CURTAIN_ID,
    DEVICE_DOOR_SENSOR_ID,
    DEVICE_HUMIDITY_SENSOR_ID,
    DEVICE_LIGHT_ID,
    DEVICE_LIGHT_SENSOR_ID,
    DEVICE_LOCK_ID,
    DEVICE_MOTION_SENSOR_ID,
    DEVICE_POWER_METER_SENSOR_ID,
    DEVICE_SCENE_CONTROLLER_ID,
    DEVICE_SWITCH2_ID,
    DEVICE_SWITCH_ID,
    DEVICE_TEMP_SENSOR_ID,
    DEVICE_THERMOSTAT_ID,
    DEVICE_UV_SENSOR_ID,
    VeraControllerData,
    new_mocked_controller,
    new_vera_api_data,
    update_device,
)

logging.basicConfig(level=logging.DEBUG)
pyvera.logger = logging.getLogger(__name__)


class VeraTest:
    def setup(self):
        self.controller_data = self.getContollerData()
        self.controller = self.controller_data.controller
        self.controller.start()

    def teardown(self):
        self.controller.stop()

    def getContollerData(self) -> VeraControllerData:
        return new_mocked_controller(new_vera_api_data())

    def update_device(self, device_id: int, key: str, value: Any):
        update_device(
            controller_data=self.controller_data,
            device_id=device_id,
            key=key,
            value=value,
        )

    def get_device_by_id(self, device_id: int):
        return self.controller.get_device_by_id(device_id)


class TestVeraBinarySensor(VeraTest):
    def do_test_sensor(self, device_id):
        """Test function."""
        device = self.get_device_by_id(device_id)  # type: VeraBinarySensor
        assert device.is_tripped is False
        assert device.is_switched_on(refresh=True) is False

        self.update_device(
            device_id=device_id, key="tripped", value="1",
        )
        assert device.is_tripped is True
        assert device.is_switched_on() is False

        self.update_device(
            device_id=device_id, key="status", value="1",
        )
        assert device.is_switched_on() is True

    def test_door_sensor(self):
        self.do_test_sensor(DEVICE_DOOR_SENSOR_ID)

    def test_motion_sensor(self):
        self.do_test_sensor(DEVICE_MOTION_SENSOR_ID)


class TestVeraLock(VeraTest):
    def test_state(self):
        device = self.get_device_by_id(DEVICE_LOCK_ID)  # type: VeraLock
        assert device.is_locked() is False
        device.lock()
        assert device.is_locked() is True
        device.unlock()
        assert device.is_locked() is False


class TestVeraThermostat(VeraTest):
    def test_state(self):
        device = self.get_device_by_id(DEVICE_THERMOSTAT_ID)  # type: VeraThermostat
        assert device.get_current_goal_temperature(refresh=True) == 8.0
        assert device.get_current_temperature(refresh=True) == 9.0
        assert device.get_hvac_mode(refresh=True) == "Off"
        assert device.get_fan_mode(refresh=True) == "Off"
        assert device.get_hvac_state(refresh=True) == "Off"

        device.set_temperature(72)
        assert device.get_current_goal_temperature() == 72

        self.update_device(device_id=DEVICE_THERMOSTAT_ID, key="temperature", value=65)
        assert device.get_current_temperature() == 65

        device.turn_auto_on()
        assert device.get_hvac_mode() == "AutoChangeOver"
        device.turn_heat_on()
        assert device.get_hvac_mode() == "HeatOn"
        device.turn_cool_on()
        assert device.get_hvac_mode() == "CoolOn"

        device.fan_on()
        assert device.get_fan_mode() == "ContinuousOn"
        device.fan_auto()
        assert device.get_fan_mode() == "Auto"
        device.fan_cycle()
        assert device.get_fan_mode() == "PeriodicOn"
        device.fan_off()
        assert device.get_fan_mode() == "Off"

        device.turn_off()
        assert device.get_hvac_mode() == "Off"


class TestVeraCurtain(VeraTest):
    def test_state(self):
        device = self.get_device_by_id(DEVICE_CURTAIN_ID)
        assert device.is_open(refresh=True) is False
        assert device.get_level(refresh=True) == 0

        device.open()
        assert device.is_open() is True
        assert device.get_level() == 100

        device.close()
        assert device.is_open() is False
        assert device.get_level() == 0

        device.set_level(50)
        self.update_device(DEVICE_CURTAIN_ID, "level", 55)
        device.stop()
        assert device.get_level() == 55
        assert device.is_open() is True


class TestVeraDimmer(VeraTest):
    def test_state(self):
        device = self.get_device_by_id(DEVICE_LIGHT_ID)  # type: VeraDimmer
        assert device.is_switched_on(refresh=True) is False
        assert device.get_brightness(refresh=True) == 0
        assert device.get_color(refresh=True) == [255, 100, 100]

        device.switch_on()
        assert device.is_switched_on() is True
        assert device.get_brightness() == 255

        device.set_brightness(66)
        assert device.get_brightness() == 66

        device.set_color([120, 130, 140])
        assert device.get_color() == [120, 130, 140]

        device.switch_off()
        assert device.get_brightness() == 0


class TestVeraSceneController(VeraTest):
    def test_state(self):
        device = self.get_device_by_id(
            DEVICE_SCENE_CONTROLLER_ID
        )  # type: VeraSceneController
        assert device.get_last_scene_id(refresh=True) == "1234"
        assert device.get_last_scene_time(refresh=True) == "10000012"
        assert device.should_poll is True

        self.update_device(DEVICE_SCENE_CONTROLLER_ID, "LastSceneID", "Id2")
        self.update_device(DEVICE_SCENE_CONTROLLER_ID, "LastSceneTime", "4444")
        assert device.get_last_scene_id() == "Id2"
        assert device.get_last_scene_time() == "4444"


class TestVeraSensor(VeraTest):
    def do_test_sensor(
        self,
        device_id: int,
        device_property: str,
        initial_value: Any,
        new_value: Any,
        variable: str,
        variable_value: Any,
    ):
        device = self.get_device_by_id(device_id)  # type: VeraSensor
        assert getattr(device, device_property) == initial_value

        self.update_device(device_id, variable, variable_value)
        assert getattr(device, device_property) == new_value

    def test_state(self):
        self.do_test_sensor(
            device_id=DEVICE_TEMP_SENSOR_ID,
            device_property="temperature",
            initial_value="57.00",
            new_value="66.00",
            variable="temperature",
            variable_value="66.00",
        )

        self.do_test_sensor(
            device_id=DEVICE_ALARM_SENSOR_ID,
            device_property="is_tripped",
            initial_value=False,
            new_value=True,
            variable="tripped",
            variable_value="1",
        )

        self.do_test_sensor(
            device_id=DEVICE_LIGHT_SENSOR_ID,
            device_property="light",
            initial_value="0",
            new_value="22",
            variable="light",
            variable_value="22",
        )

        self.do_test_sensor(
            device_id=DEVICE_UV_SENSOR_ID,
            device_property="light",
            initial_value="0",
            new_value="23",
            variable="light",
            variable_value="23",
        )

        self.do_test_sensor(
            device_id=DEVICE_HUMIDITY_SENSOR_ID,
            device_property="humidity",
            initial_value="0",
            new_value="40",
            variable="humidity",
            variable_value="40",
        )

        self.do_test_sensor(
            device_id=DEVICE_POWER_METER_SENSOR_ID,
            device_property="power",
            initial_value="0",
            new_value="50",
            variable="watts",
            variable_value="50",
        )


class TestVeraSwitch(VeraTest):
    def test_state(self):
        device = self.get_device_by_id(DEVICE_SWITCH_ID)
        assert device.is_switched_on() is False
        device.switch_on()
        assert device.is_switched_on() is True
        device.switch_off()
        assert device.is_switched_on() is False

        device = self.get_device_by_id(DEVICE_SWITCH2_ID)
        assert device.is_switched_on() is False
        device.switch_on()
        assert device.is_switched_on() is True
        device.switch_off()
        assert device.is_switched_on() is False
