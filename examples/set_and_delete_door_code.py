#!/usr/bin/env python
"""Example script."""

# Parse Arguments
# Import project path
import argparse
import os
import sys

# Import pyvera
from pyvera import VeraController, VeraLock


def main() -> None:
    """Run main code entrypoint."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))

    parser = argparse.ArgumentParser(description="show-lock-info")
    parser.add_argument(
        "-u", "--url", help="Vera URL, e.g. http://192.168.1.161:3480", required=True
    )
    # args = parser.parse_args()

    # Start the controller
    controller = VeraController('http://192.168.112.202:3480')
    controller.start()

    try:
        # Get a list of all the devices on the vera controller
        all_devices = controller.get_devices()

        # Look over the list and find the lock devices
        for device in all_devices:
            if isinstance(device, VeraLock):
                # show exisiting door codes
                print("Existing door codes\n {}".format(device.get_pin_codes())) 
                
                # set a new door code
                result = device.set_new_pin(name="John Doe", pin=12121213)
                
                # printing the status code and error if any
                print("status:"+str(result.status_code), result.text)
                
                # confirm door code has been added
                print("Updated Door codes\n {}".format(device.get_pin_codes()))

    finally:
        # Stop the subscription listening thread so we can quit
        controller.stop()


if __name__ == "__main__":
    main()
