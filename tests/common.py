"""Common code for tests."""

from copy import deepcopy
import json
import re
from typing import Any, List, NamedTuple, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from _pytest.fixtures import FixtureRequest
from pyvera import (
    CATEGORY_ARMABLE,
    CATEGORY_CURTAIN,
    CATEGORY_DIMMER,
    CATEGORY_GARAGE_DOOR,
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
import requests
import responses

VeraApiData = NamedTuple(
    "VeraApiData", [("sdata", dict), ("status", dict), ("lu_sdata", dict)]
)

VeraControllerData = NamedTuple(
    "ControllerData", [("api_data", VeraApiData), ("controller", VeraController)]
)


def new_vera_api_data() -> VeraApiData:
    """Create new api data object."""
    return VeraApiData(
        sdata=deepcopy(RESPONSE_SDATA),
        status=deepcopy(RESPONSE_STATUS),
        lu_sdata=deepcopy(RESPONSE_LU_SDATA),
    )


def find_device_object(device_id: int, data_list: List[dict]) -> Optional[dict]:
    """Find a vera device object in a list of devices."""
    for device in data_list:
        if device.get("id") == device_id:
            return device

    return None


def get_device(device_id: int, api_data: VeraApiData) -> Optional[dict]:
    """Find a vera device."""
    return find_device_object(device_id, api_data.sdata.get("devices", []))


def get_device_status(device_id: int, api_data: VeraApiData) -> Optional[dict]:
    """Find a vera device status."""
    return find_device_object(device_id, api_data.status.get("devices", []))


def set_device_status(
    device_id: int, api_data: VeraApiData, key: str, value: Any
) -> None:
    """Set the status of a vera device."""
    device = get_device(device_id, api_data)
    device_status = get_device_status(device_id, api_data)

    if not device or not device_status:
        return

    device_status[key] = value
    device[key] = value

    device_status["states"] = device_status["states"] or []

    # Get the current state or create a new one.
    state: dict = next(
        iter([s for s in device_status["states"] if s["variable"] == key]), {}
    )

    # Update current states to exclude the one we are changing.
    device_status["states"] = [
        s for s in device_status["states"] if s["variable"] != key
    ]

    # Add the updated state to the list of states.
    state.update({"variable": key, "value": value})
    device_states = device_status["state"] = device_status.get("state", [])
    device_states.append(state)


def update_device(
    controller_data: VeraControllerData,
    device_id: int,
    key: str,
    value: Any,
    push: bool = True,
) -> None:
    """Update a vera device with a specific key/value."""
    device = get_device(device_id, controller_data.api_data)
    assert device, "Failed to find device with device id %d" % device_id

    device_status = get_device_status(device_id, controller_data.api_data)
    assert device_status, "Failed to find device status with device id %d" % device_id

    lu_data = controller_data.api_data.lu_sdata
    lu_data_devices = lu_data["devices"] = lu_data.get("devices", [])
    lu_data_devices.append(device)

    controller_data.api_data.lu_sdata["loadtime"] = "now"
    controller_data.api_data.lu_sdata["dataversion"] += 1

    controller_data.api_data.status["LoadTime"] = "now"
    controller_data.api_data.status["DataVersion"] += 1

    device_status[key] = value
    device[key] = value

    device_status["states"] = device_status["states"] or []

    # Get the current state or create a new one.
    state: dict = next(
        iter([s for s in device_status["states"] if s["variable"] == key]), {}
    )

    # Update current states to exclude the one we are changing.
    device_status["states"] = [
        s for s in device_status["states"] if s["variable"] != key
    ]

    # Add the updated state to the list of states.
    state.update({"variable": key, "value": value})
    device_status["states"].append(state)

    if push:
        publish_device_status(controller_data.controller, device_status)


def publish_device_status(controller: VeraController, device_status: dict) -> None:
    """Instruct pyvera to notify objects that data changed for a device."""
    # pylint: disable=protected-access
    controller.subscription_registry._event([device_status], [])


ResponsesResponse = Tuple[int, dict, str]


def handle_lu_action(payload: dict, api_data: VeraApiData) -> ResponsesResponse:
    """Handle lu_action requests."""
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

    if service_id == "urn:upnp-org:serviceId:SwitchPower1" and action == "SetTarget":
        status_variable_name = "status"
    elif (
        service_id == "urn:upnp-org:serviceId:Dimming1"
        and action == "SetLoadLevelTarget"
    ):
        status_variable_name = "level"
    elif (
        service_id == "urn:micasaverde-com:serviceId:SecuritySensor1"
        and action == "SetArmed"
    ):
        status_variable_name = "armed"
    elif (
        service_id == "urn:upnp-org:serviceId:WindowCovering1"
        and action == "SetLoadLevelTarget"
    ):
        status_variable_name = "level"
    elif (
        service_id == "urn:micasaverde-com:serviceId:DoorLock1"
        and action == "NewTarget"
    ):
        status_variable_name = "locked"
    elif (
        service_id == "urn:upnp-org:serviceId:HVAC_UserOperatingMode1"
        and action == "SetModeTarget"
    ):
        status_variable_name = "mode"
    elif (
        service_id == "urn:upnp-org:serviceId:HVAC_FanOperatingMode1"
        and action == "SetMode"
    ):
        status_variable_name = "fanmode"
    elif service_id == "urn:upnp-org:serviceId:TemperatureSetpoint1_Cool":
        pass
    elif service_id == "urn:upnp-org:serviceId:TemperatureSetpoint1_Heat":
        pass
    elif (
        service_id == "urn:upnp-org:serviceId:TemperatureSetpoint1"
        and action == "SetCurrentSetpoint"
    ):
        status_variable_name = "setpoint"
    elif (
        service_id == "urn:micasaverde-com:serviceId:Color1" and action == "SetColorRGB"
    ):
        status_variable_name = "CurrentColor"

    device = get_device(device_id, api_data) or {}
    status = get_device_status(device_id, api_data) or {}
    status["states"] = []

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

    return 200, {}, ""


def handle_variable_get(payload: dict, api_data: VeraApiData) -> ResponsesResponse:
    """Handle variable_get requests."""
    device_id = payload.get("DeviceNum")
    variable = payload.get("Variable")

    if device_id and variable:
        status = get_device_status(int(device_id), api_data) or {}
        for state in status.get("states", []):
            if state.get("variable") == variable:
                # return state.get("value")
                return 200, {}, state.get("value")

    return 200, {}, ""


def handle_request(
    req: requests.PreparedRequest, api_data: VeraApiData
) -> ResponsesResponse:
    """Handle a request for data from the controller."""
    url_parts = urlparse(req.url)
    qs_parts: dict = parse_qs(url_parts.query)
    payload = {}
    for key, value in qs_parts.items():
        payload[key] = value[0]

    payload_id = payload.get("id")

    response: ResponsesResponse = (200, {}, "")
    if payload_id == "sdata":
        response = 200, {}, json.dumps(api_data.sdata)
    if payload_id == "status":
        response = 200, {}, json.dumps(api_data.status)
    if payload_id == "lu_sdata":
        response = 200, {}, json.dumps(api_data.lu_sdata)
    if payload_id == "action":
        response = 200, {}, json.dumps({})
    if payload_id == "variableget":
        response = handle_variable_get(payload, api_data)
    if payload_id == "lu_action":
        response = handle_lu_action(payload, api_data)

    return response


class VeraControllerFactory:
    """Manages the creation of mocked controllers."""

    def __init__(self, pytest_req: FixtureRequest, rsps: responses.RequestsMock):
        """Init object."""
        self.pytest_req = pytest_req
        self.rsps = rsps

    def new_instance(self, api_data: VeraApiData) -> VeraControllerData:
        """Create new instance of controller."""
        base_url = "http://127.0.0.1:123"

        def callback(req: requests.PreparedRequest) -> ResponsesResponse:
            nonlocal api_data
            return handle_request(req, api_data)

        self.rsps.add_callback(
            method=responses.GET,
            url=re.compile(f"{base_url}/data_request?.*"),
            callback=callback,
            content_type="application/json",
        )

        controller = VeraController("http://127.0.0.1:123")
        controller.data_request({"id": "sdata"})
        controller.start()

        # Stop the controller after the test stops and fixture is torn down.
        self.pytest_req.addfinalizer(controller.stop)

        return VeraControllerData(api_data=api_data, controller=controller)


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
DEVICE_GARAGE_DOOR_ID = 47
DEVICE_LOCK_ID = 10
DEVICE_THERMOSTAT_ID = 11
DEVICE_CURTAIN_ID = 12
DEVICE_SCENE_CONTROLLER_ID = 13
DEVICE_LIGHT_SENSOR_ID = 14
DEVICE_UV_SENSOR_ID = 15
DEVICE_HUMIDITY_SENSOR_ID = 16
DEVICE_POWER_METER_SENSOR_ID = 17
DEVICE_GENERIC_DEVICE_ID = 19

CATEGORY_UNKNOWN = 1234

RESPONSE_SDATA = {
    "scenes": [{"id": SCENE1_ID, "name": "scene1", "active": 0, "root": 0}],
    "temperature": 23,
    "model": "fake_model_number",
    "version": "fake_version_number",
    "serial_number": "fake_serial_number",
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
            "status": "0",
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
            "status": "0",
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
            "temperature": 57.00,
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
            "name": "Garage door 1",
            "altid": "5",
            "id": DEVICE_GARAGE_DOOR_ID,
            "category": CATEGORY_GARAGE_DOOR,
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
        {
            "name": "Power meter sensor 1",
            "altid": "5",
            "id": DEVICE_GENERIC_DEVICE_ID,
            "category": CATEGORY_GENERIC,
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

RESPONSE_STATUS: dict = {
    "LoadTime": None,
    "DataVersion": 1,
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
            "id": DEVICE_GARAGE_DOOR_ID,
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
        {
            "id": DEVICE_GENERIC_DEVICE_ID,
            "states": [],
            "Jobs": [],
            "PendingJobs": 0,
            "tooltip": {"display": 0},
            "status": -1,
        },
    ],
}

RESPONSE_LU_SDATA: dict = {"loadtime": None, "dataversion": 1, "devices": []}

RESPONSE_SCENES: dict = {}
