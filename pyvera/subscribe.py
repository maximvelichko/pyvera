"""Module to listen for vera events."""
import collections
import json
import logging
import time
import threading
import requests

# How long to wait before retrying Vera
SUBSCRIPTION_RETRY = 10

# Vera state codes see http://wiki.micasaverde.com/index.php/Luup_Requests
STATE_NO_JOB = -1
STATE_JOB_WAITING_TO_START = 0
STATE_JOB_IN_PROGRESS = 1
STATE_JOB_ERROR = 2
STATE_JOB_ABORTED = 3
STATE_JOB_DONE = 4
STATE_JOB_WAITING_FOR_CALLBACK = 5
STATE_JOB_REQUEUE = 6
STATE_JOB_PENDING_DATA = 7

STATE_NOT_PRESENT = 999

# Get the logger for use in this module
logger = logging.getLogger(__name__)

class PyveraError(Exception):
    pass

class SubscriptionRegistry(object):
    """Class for subscribing to wemo events."""

    def __init__(self):
        """Setup subscription."""
        self._devices = collections.defaultdict(list)
        self._callbacks = collections.defaultdict(list)
        self._exiting = False
        self._poll_thread = None

    def register(self, device, callback):
        """Register a callback.

        device: device to be updated by subscription
        callback: callback for notification of changes
        """
        if not device:
            logger.error("Received an invalid device: %r", device)
            return

        logger.debug("Subscribing to events for %s", device.name)
        self._devices[device.vera_device_id].append(device)
        self._callbacks[device].append(callback)


    def unregister(self, device, callback):
        """Remove a registered change callback.

        device: device that has the subscription
        callback: callback used in original registration
        """
        if not device:
            logger.error("Received an invalid device: %r", device)
            return

        logger.debug("Removing subscription for {}".format(device.name))
        self._callbacks[device].remove(callback)
        self._devices[device.vera_device_id].remove(device)


    def _event(self, device_data_list, device_alert_list):
        # Find unique device_ids that have data across both device_data and alert_data
        device_ids = set()
        [device_ids.add(int(device_data['id'])) for device_data in device_data_list]
        [device_ids.add(int(alert_data['PK_Device'])) for alert_data in device_alert_list]

        for device_id in device_ids:
            device_list = self._devices.get(device_id, ())
            device_datas = [data for data in device_data_list if int(data['id']) == device_id]
            device_alerts = [alert for alert in device_alert_list if int(alert['PK_Device']) == device_id]

            device_data = device_datas[0] if device_datas else {}

            for device in device_list:
                self._event_device(device, device_data, device_alerts)


    def _event_device(self, device, device_data, device_alerts):
        if device is None:
            return
        # Vera can send an update status STATE_NO_JOB but
        # with a comment about sending a command
        state = int(device_data.get('state', STATE_NOT_PRESENT))
        comment = device_data.get('comment', '')
        sending = comment.find('Sending') >= 0
        logger.debug("Event: %s, state %s, alerts %s, %s",
                  device.name,
                  state,
                  len(device_alerts),
                  json.dumps(device_data))
        device.set_alerts(device_alerts)
        if sending and state == STATE_NO_JOB:
            state = STATE_JOB_WAITING_TO_START
        if (state == STATE_JOB_IN_PROGRESS and
                device.__class__.__name__ == 'VeraLock'):
            # VeraLocks don't complete
            # so we detect if we are done from the comment field.
            # This is really just a workaround for a vera bug
            # and it does mean that a device name
            # cannot contain the SUCCESS! string (very unlikely)
            # since the name is also returned in the comment for
            # some status messages
            success = comment.find('SUCCESS!') >= 0
            if success:
                logger.debug('Lock success found, job is done')
                state = STATE_JOB_DONE

        if (
                state == STATE_JOB_WAITING_TO_START or
                state == STATE_JOB_IN_PROGRESS or
                state == STATE_JOB_WAITING_FOR_CALLBACK or
                state == STATE_JOB_REQUEUE or
                state == STATE_JOB_PENDING_DATA):
            return
        if not (state == STATE_JOB_DONE or
                state == STATE_NOT_PRESENT or
                state == STATE_NO_JOB or
                (state == STATE_JOB_ERROR and
                    comment.find('Setting user configuration'))):
            logger.error("Device %s, state %s, %s",
                      device.name,
                      state,
                      comment)
            return
        device.update(device_data)
        for callback in self._callbacks.get(device, ()):
            try:
                callback(device)
            except:
                # (Very) broad check to not let loosely-implemented callbacks
                # kill our polling thread. They should be catching their own
                # errors, so if it gets back to us, just log it and move on.
                logger.exception(
                    "Unhandled exception in callback for device #%s (%s)",
                    str(device.device_id), device.name)

    def join(self):
        """Don't allow the main thread to terminate until we have."""
        self._poll_thread.join()

    def start(self):
        """Start a thread to handle Vera blocked polling."""
        self._poll_thread = threading.Thread(target=self._run_poll_server,
                                             name='Vera Poll Thread')
        self._poll_thread.deamon = True
        self._poll_thread.start()

    def stop(self):
        """Tell the subscription thread to terminate."""
        self._exiting = True
        self.join()
        logger.info("Terminated thread")

    def _run_poll_server(self):
        from pyvera import get_controller
        controller = get_controller()
        timestamp = {'dataversion': 1, 'loadtime': 0}
        device_data = []
        alert_data = []
        while not self._exiting:
            try:
                logger.debug("Polling for Vera changes")
                device_data, new_timestamp = (
                    controller.get_changed_devices(timestamp))
                if new_timestamp['dataversion'] != timestamp['dataversion']:
                    alert_data = controller.get_alerts(timestamp)
                timestamp = new_timestamp
            except requests.RequestException as ex:
                logger.debug("Caught RequestException: %s", str(ex))
                pass
            except PyveraError as ex:
                logger.debug("Non-fatal error in poll: %s", str(ex))
                pass
            except Exception as ex:
                logger.exception("Vera poll thread general exception: %s",
                    str(ex))
                raise
            else:
                logger.debug("Poll returned")
                if not self._exiting:
                    if device_data or alert_data:
                        self._event(device_data, alert_data)
                    else:
                        logger.debug("No changes in poll interval")
                    time.sleep(1)

                continue

            # After error, discard timestamp for fresh update. pyvera issue #89
            timestamp = {'dataversion': 1, 'loadtime': 0}
            logger.info("Could not poll Vera - will retry in %ss",
                     SUBSCRIPTION_RETRY)
            time.sleep(SUBSCRIPTION_RETRY)

        logger.info("Shutdown Vera Poll Thread")
