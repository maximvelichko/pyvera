#!/usr/bin/env python

# Import project path
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), '..'))

# Import pyvera
import pyvera

import time

# Parse Arguments
import argparse
parser = argparse.ArgumentParser(description='lock-all-doors-with-status')
parser.add_argument('-u', '--url', help="Vera URL, e.g. http://192.168.1.161:3480", required=True)
args = parser.parse_args()

# Define a callback that runs each time a device changes state
def device_info_callback(vera_device):
    # Do what we want with the changed device information
    print('{}_{}: locked={}'.format(vera_device.name, vera_device.device_id, vera_device.is_locked()))

# Start the controller
controller, _ = pyvera.init_controller(args.url)

try:
    # Get a list of all the devices on the vera controller
    all_devices = controller.get_devices()

    # Look over the list and find the lock devices
    lock_devices = []
    for device in all_devices:
        if isinstance(device, pyvera.VeraLock):
            # Register a callback that runs when the info for that device is updated
            controller.register(device, device_info_callback)
            print('Initially, {}_{}: locked={}'.format(device.name, device.device_id, device.is_locked()))
            lock_devices.append(device)
            if not device.is_locked():
                device.lock()

    # Loop until someone hits Ctrl-C to interrupt the listener
    try:
        all_locked = False
        while not all_locked:
            time.sleep(1)
            all_locked = True
            for device in lock_devices:
                if not device.is_locked():
                    all_locked = False
        print('All doors are now locked')

    except KeyboardInterrupt:
        print('Got interrupted by user')
        pass

    # Unregister our callback
    for device in lock_devices:
        controller.unregister(device, device_info_callback)

finally:
    # Stop the subscription listening thread so we can quit
    controller.stop()

