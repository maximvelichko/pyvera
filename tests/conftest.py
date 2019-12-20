"""Global pytest fixtures."""
from typing import Generator

from _pytest.fixtures import FixtureRequest
import pytest
import responses

from .common import VeraControllerData, VeraControllerFactory, new_vera_api_data


@pytest.fixture(name="vera_controller_factory")
def fixture_vera_controller_factory(
    request: FixtureRequest,
) -> Generator[VeraControllerFactory, None, None]:
    """Get a controller factory."""
    with responses.RequestsMock() as rsps:
        yield VeraControllerFactory(request, rsps)


@pytest.fixture(name="vera_controller_data")
def fixture_vera_controller_data(
    vera_controller_factory: VeraControllerFactory,
) -> VeraControllerData:
    """Get mocked controller data."""
    return vera_controller_factory.new_instance(new_vera_api_data())
