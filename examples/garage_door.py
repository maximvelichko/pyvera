#!/usr/bin/env python

# Import project path
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), '..'))

# Import pyvera
import pyvera

# Parse Arguments
import argparse
parser = argparse.ArgumentParser(description='list-devices')
parser.add_argument('-u', '--url', help="Vera URL, e.g. http://192.168.1.161:3480", required=True)
parser.add_argument('--close', help="Close garage door(s)", action="store_true")
args = parser.parse_args()

# Start the controller
controller, _ = pyvera.init_controller(args.url)

try:
    # Get a list of all the devices on the vera controller
    all_devices = controller.get_devices()

    # Open/close all garage doors.
    for device in all_devices:
        if isinstance(device, pyvera.VeraGarageDoor):
            if args.close:
                device.switch_off()
            else:
                device.switch_on()

finally:
    # Stop the subscription listening thread so we can quit
    controller.stop()
