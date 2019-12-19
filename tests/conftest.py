"""Global pytest fixtures."""
import pytest
import responses

from .common import VeraControllerFactory, new_vera_api_data


@pytest.fixture(name="vera_controller_factory")
def fixture_vera_controller_factory(request):
    """Get a controller factory."""
    with responses.RequestsMock() as rsps:
        yield VeraControllerFactory(request, rsps)


@pytest.fixture(name="vera_controller_data")
def fixture_vera_controller_data(vera_controller_factory: VeraControllerFactory):
    """Get mocked controller data."""
    return vera_controller_factory.new_instance(new_vera_api_data())
