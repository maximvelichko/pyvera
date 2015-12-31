"""Module to listen for vera events."""
import collections
import functools
import logging
import time
import threading
import requests

SUBSCRIPTION_RETRY = 60
# Time to wait for event in seconds

LOG = logging.getLogger(__name__)

class SubscriptionRegistry(object):
    """Class for subscribing to wemo events."""

    def __init__(self):
        self._devices = {}
        self._callbacks = collections.defaultdict(list)
        self._exiting = False
        self._poll_thread = None

    def register(self, device):
        if not device:
            LOG.error("Received an invalid device: %r", device)
            return

        LOG.info("Subscribing to events for %s", device.name)
        # Provide a function to register a callback when the device changes
        # state
        device.register_listener = functools.partial(self.on, device, None)
        self._devices[device.vera_device_id] = device

    def _event(self, devices):
        LOG.info("Got vera event for devices %s", [d.name for d in devices])
        # if not devices specified - callback everything
        if devices:
            for device in devices:
                for callback in self._callbacks.get(device, ()):
                    callback(device)
        else:
            for device, callbacks in self._callbacks.items():
                for callback in callbacks:
                    callback(device)

    def join(self):
        self._poll_thread.join()

    def on(self, device, callback):
        self._callbacks[device].append((callback))

    def start(self):
        self._poll_thread = threading.Thread(target=self._run_poll_server,
                                             name='Vera Poll Thread')
        self._poll_thread.deamon = True
        self._poll_thread.start()

    def stop(self):
        self._exiting = True

    def _run_poll_server(self):
        from pyvera import get_controller
        controller = get_controller()
        timestamp = controller.get_initial_timestamp()
        while not self._exiting:
            try:
                device_ids, timestamp = controller.get_changed_devices(timestamp)
                devices = [self._devices.get(int(id)) for id in device_ids]
                self._event(devices)
            except requests.RequestException:
                LOG.info("Could not contact Vera - will retry in %ss", SUBSCRIPTION_RETRY)
                time.sleep(SUBSCRIPTION_RETRY)

        LOG.info("Shutdown Vera Poll Thread")

