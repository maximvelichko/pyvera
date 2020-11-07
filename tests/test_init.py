"""Test module."""
import logging
import time
from typing import Any, NamedTuple, cast
from unittest.mock import MagicMock

import pytest
import pyvera
from pyvera import (
    CATEGORY_LOCK,
    STATE_JOB_IN_PROGRESS,
    STATE_NO_JOB,
    SubscriptionRegistry,
    VeraBinarySensor,
    VeraController,
    VeraCurtain,
    VeraDimmer,
    VeraLock,
    VeraSceneController,
    VeraSensor,
    VeraSwitch,
    VeraThermostat,
)

from .common import (
    DEVICE_ALARM_SENSOR_ID,
    DEVICE_CURTAIN_ID,
    DEVICE_DOOR_SENSOR_ID,
    DEVICE_GARAGE_DOOR_ID,
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
    update_device,
)

logging.basicConfig(level=logging.DEBUG)
pyvera.LOG = logging.getLogger(__name__)


def test_controller_refresh_data(vera_controller_data: VeraControllerData) -> None:
    """Test function."""
    controller = vera_controller_data.controller

    assert not controller.model
    assert not controller.version
    assert not controller.serial_number
    controller.refresh_data()
    assert controller.model == "fake_model_number"
    assert controller.version == "fake_version_number"
    assert controller.serial_number == "fake_serial_number"


# pylint: disable=protected-access
def test__event_device_for_vera_lock_status() -> None:
    """Test function."""
    registry = SubscriptionRegistry()
    registry.set_controller(MagicMock(spec=VeraController))
    mock_lock = MagicMock(spec=VeraLock)
    mock_lock.name = MagicMock(return_value="MyTestDeadbolt")

    # Deadbolt changing but not done
    device_json: dict = {"state": STATE_JOB_IN_PROGRESS}
    registry._event_device(mock_lock, device_json, [])
    mock_lock.update.assert_not_called()

    # Deadbolt progress with reset state but not done
    device_json = {
        "state": STATE_NO_JOB,
        "comment": "MyTestDeadbolt: Sending the Z-Wave command after 0 retries",
    }
    registry._event_device(mock_lock, device_json, [])
    mock_lock.update.assert_not_called()

    # Deadbolt progress locked but not done
    device_json = {
        "state": STATE_JOB_IN_PROGRESS,
        "locked": "1",
        "comment": "MyTestDeadbolt",
    }
    registry._event_device(mock_lock, device_json, [])
    mock_lock.update.assert_not_called()

    # Deadbolt progress with status but not done
    device_json = {
        "state": STATE_JOB_IN_PROGRESS,
        "comment": "MyTestDeadbolt: Please wait! Polling node",
    }
    registry._event_device(mock_lock, device_json, [])
    mock_lock.update.assert_not_called()

    # Deadbolt progress complete
    device_json = {
        "state": STATE_JOB_IN_PROGRESS,
        "locked": "1",
        "comment": "MyTestDeadbolt: SUCCESS! Successfully polled node",
        "deviceInfo": {"category": CATEGORY_LOCK},
    }
    registry._event_device(mock_lock, device_json, [])
    mock_lock.update.assert_called_once_with(device_json)


def test_polling(vera_controller_data: VeraControllerData) -> None:
    """Test function."""
    controller = vera_controller_data.controller

    callback_mock = MagicMock()
    device = cast(VeraSensor, controller.get_device_by_id(DEVICE_TEMP_SENSOR_ID))
    controller.register(device, callback_mock)

    # Data updated, poll didn't run yet.
    update_device(
        controller_data=vera_controller_data,
        device_id=DEVICE_TEMP_SENSOR_ID,
        key="temperature",
        value=66.00,
        push=False,
    )
    assert device.temperature == 57.00
    callback_mock.assert_not_called()

    # Poll ran, new data, device updated.
    time.sleep(1.1)
    assert device.temperature == 66.00
    callback_mock.assert_called_with(device)
    callback_mock.reset_mock()

    # Poll ran, no new data.
    time.sleep(1)
    callback_mock.assert_not_called()

    # Poll ran, new date, device updated.
    update_device(
        controller_data=vera_controller_data,
        device_id=DEVICE_TEMP_SENSOR_ID,
        key="temperature",
        value=77.00,
        push=False,
    )
    callback_mock.assert_not_called()
    time.sleep(1)
    callback_mock.assert_called_with(device)


def test_controller_custom_subscription_registry() -> None:
    """Test function."""

    class CustomSubscriptionRegistry(pyvera.AbstractSubscriptionRegistry):
        """Test registry."""

        def start(self) -> None:
            """Start the polling."""

        def stop(self) -> None:
            """Stop the polling."""

    controller = VeraController("URL", CustomSubscriptionRegistry())
    assert controller.subscription_registry.get_controller() == controller


def test_controller_register_unregister(
    vera_controller_data: VeraControllerData,
) -> None:
    """Test function."""
    controller = vera_controller_data.controller
    device = cast(VeraSensor, controller.get_device_by_id(DEVICE_TEMP_SENSOR_ID))
    callback_mock = MagicMock()

    assert device.temperature == 57.00

    # Device not registered, device is not update.
    update_device(
        controller_data=vera_controller_data,
        device_id=DEVICE_TEMP_SENSOR_ID,
        key="temperature",
        value=66.00,
    )
    assert device.temperature == 57.00
    callback_mock.assert_not_called()
    callback_mock.mock_reset()

    # Device registered, device is updated.
    controller.register(device, callback_mock)
    update_device(
        controller_data=vera_controller_data,
        device_id=DEVICE_TEMP_SENSOR_ID,
        key="temperature",
        value=66.00,
    )
    assert device.temperature == 66.00
    callback_mock.assert_called_with(device)
    callback_mock.reset_mock()

    # Device unregistered, device is updated.
    controller.unregister(device, callback_mock)
    update_device(
        controller_data=vera_controller_data,
        device_id=DEVICE_TEMP_SENSOR_ID,
        key="temperature",
        value=111111.11,
    )
    assert device.temperature == 66.00
    callback_mock.assert_not_called()


@pytest.mark.parametrize("device_id", (DEVICE_DOOR_SENSOR_ID, DEVICE_MOTION_SENSOR_ID))
def test_binary_sensor(
    vera_controller_data: VeraControllerData, device_id: int
) -> None:
    """Test function."""
    controller = vera_controller_data.controller
    device = cast(VeraBinarySensor, controller.get_device_by_id(device_id))
    controller.register(device, lambda device: None)

    assert device.is_tripped is False
    assert device.is_switched_on(refresh=True) is False

    update_device(
        controller_data=vera_controller_data,
        device_id=device_id,
        key="tripped",
        value="1",
    )
    assert device.is_tripped is True
    assert device.is_switched_on() is False

    update_device(
        controller_data=vera_controller_data,
        device_id=device_id,
        key="status",
        value="1",
    )
    assert device.is_switched_on() is True


def test_lock(vera_controller_data: VeraControllerData) -> None:
    """Test function."""
    controller = vera_controller_data.controller
    device = cast(VeraLock, controller.get_device_by_id(DEVICE_LOCK_ID))
    controller.register(device, lambda device: None)

    assert device.is_locked() is False
    device.lock()
    assert device.is_locked() is True
    device.unlock()
    assert device.is_locked() is False


def test_thermostat(vera_controller_data: VeraControllerData) -> None:
    """Test function."""
    controller = vera_controller_data.controller
    device = cast(VeraThermostat, controller.get_device_by_id(DEVICE_THERMOSTAT_ID))
    controller.register(device, lambda device: None)

    assert device.get_current_goal_temperature(refresh=True) == 8.0
    assert device.get_current_temperature(refresh=True) == 9.0
    assert device.get_hvac_mode(refresh=True) == "Off"
    assert device.get_fan_mode(refresh=True) == "Off"
    assert device.get_hvac_state(refresh=True) == "Off"

    device.set_temperature(72)
    assert device.get_current_goal_temperature() == 72

    update_device(
        controller_data=vera_controller_data,
        device_id=DEVICE_THERMOSTAT_ID,
        key="temperature",
        value=65,
    )
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


def test_curtain(vera_controller_data: VeraControllerData) -> None:
    """Test function."""
    controller = vera_controller_data.controller
    device = cast(VeraCurtain, controller.get_device_by_id(DEVICE_CURTAIN_ID))
    controller.register(device, lambda device: None)

    assert device.is_open(refresh=True) is False
    assert device.get_level(refresh=True) == 0

    device.open()
    assert device.is_open() is True
    assert device.get_level() == 100

    device.close()
    assert device.is_open() is False
    assert device.get_level() == 0

    device.set_level(50)
    update_device(vera_controller_data, DEVICE_CURTAIN_ID, "level", 55)
    device.stop()
    assert device.get_level() == 55
    assert device.is_open() is True


def test_dimmer(vera_controller_data: VeraControllerData) -> None:
    """Test function."""
    controller = vera_controller_data.controller
    device = cast(VeraDimmer, controller.get_device_by_id(DEVICE_LIGHT_ID))
    controller.register(device, lambda device: None)

    assert device.is_switched_on(refresh=True) is False
    assert device.get_brightness(refresh=True) == 0
    assert device.get_color(refresh=True) == [255, 100, 100]

    device.switch_on()
    assert device.is_switched_on() is True

    device.set_brightness(66)
    assert device.get_brightness() == 66

    device.switch_off()
    device.switch_on()
    assert device.get_brightness() == 66

    device.set_color([120, 130, 140])
    assert device.get_color() == [120, 130, 140]

    device.switch_off()
    assert device.is_switched_on() is False


def test_scene_controller(vera_controller_data: VeraControllerData) -> None:
    """Test function."""
    controller = vera_controller_data.controller
    device = cast(
        VeraSceneController, controller.get_device_by_id(DEVICE_SCENE_CONTROLLER_ID)
    )
    controller.register(device, lambda device: None)

    assert device.get_last_scene_id(refresh=True) == "1234"
    assert device.get_last_scene_time(refresh=True) == "10000012"
    assert device.should_poll is True

    update_device(
        vera_controller_data, DEVICE_SCENE_CONTROLLER_ID, "LastSceneID", "Id2"
    )
    update_device(
        vera_controller_data, DEVICE_SCENE_CONTROLLER_ID, "LastSceneTime", "4444"
    )
    assert device.get_last_scene_id(refresh=False) == "1234"
    assert device.get_last_scene_time(refresh=False) == "10000012"
    assert device.get_last_scene_id(refresh=True) == "Id2"
    assert device.get_last_scene_time(refresh=True) == "4444"


SensorParam = NamedTuple(
    "SensorParam",
    (
        ("device_id", int),
        ("device_property", str),
        ("initial_value", Any),
        ("new_value", Any),
        ("variable", str),
        ("variable_value", Any),
    ),
)


@pytest.mark.parametrize(
    "param",
    (
        SensorParam(
            device_id=DEVICE_TEMP_SENSOR_ID,
            device_property="temperature",
            initial_value=57.00,
            new_value=66.00,
            variable="temperature",
            variable_value=66.00,
        ),
        SensorParam(
            device_id=DEVICE_ALARM_SENSOR_ID,
            device_property="is_tripped",
            initial_value=False,
            new_value=True,
            variable="tripped",
            variable_value="1",
        ),
        SensorParam(
            device_id=DEVICE_LIGHT_SENSOR_ID,
            device_property="light",
            initial_value="0",
            new_value="22",
            variable="light",
            variable_value="22",
        ),
        SensorParam(
            device_id=DEVICE_UV_SENSOR_ID,
            device_property="light",
            initial_value="0",
            new_value="23",
            variable="light",
            variable_value="23",
        ),
        SensorParam(
            device_id=DEVICE_HUMIDITY_SENSOR_ID,
            device_property="humidity",
            initial_value="0",
            new_value="40",
            variable="humidity",
            variable_value="40",
        ),
        SensorParam(
            device_id=DEVICE_POWER_METER_SENSOR_ID,
            device_property="power",
            initial_value="0",
            new_value="50",
            variable="watts",
            variable_value="50",
        ),
    ),
)
def test_sensor(vera_controller_data: VeraControllerData, param: SensorParam) -> None:
    """Test function."""
    controller = vera_controller_data.controller
    device = cast(VeraSensor, controller.get_device_by_id(param.device_id))
    controller.register(device, lambda device: None)
    assert getattr(device, param.device_property) == param.initial_value

    update_device(
        controller_data=vera_controller_data,
        device_id=param.device_id,
        key=param.variable,
        value=param.variable_value,
    )
    assert getattr(device, param.device_property) == param.new_value


@pytest.mark.parametrize(
    "device_id", (DEVICE_SWITCH_ID, DEVICE_SWITCH2_ID, DEVICE_GARAGE_DOOR_ID)
)
def test_switch(vera_controller_data: VeraControllerData, device_id: int) -> None:
    """Test function."""
    controller = vera_controller_data.controller
    device = cast(VeraSwitch, controller.get_device_by_id(device_id))
    controller.register(device, lambda device: None)

    assert device.is_switched_on() is False
    device.switch_on()
    assert device.is_switched_on() is True
    device.switch_off()
    assert device.is_switched_on() is False
