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

    parser = argparse.ArgumentParser(description="set-and-delete-door-code")
    parser.add_argument(
        "-u", "--url", help="Vera URL, e.g. http://192.168.1.161:3480;", required=True
    )
    parser.add_argument("-n", "--name", help='Name eg: "John Doe"', required=True)
    parser.add_argument("-p", "--pin", help='Pin eg: "12345678"', required=True)
    args = parser.parse_args()

    # Start the controller
    controller = VeraController(args.url)
    controller.start()

    try:
        # Get a list of all the devices on the vera controller
        all_devices = controller.get_devices("Doorlock")

        # Look over the list and find the lock devices
        for device in all_devices:
            if isinstance(device, VeraLock):
                # show exisiting door codes
                print("Existing door codes:\n {}".format(device.get_pin_codes()))

                # set a new door code
                result = device.set_new_pin(name=args.name, pin=args.pin)

                # printing the status code and error if any for debug logs
                # print("status:"+str(result.status_code), result.text)

                if result.status_code == 200:
                    print("\nCommand succesfully sent to Lock \
                    \nWait for the lock to process the request")
                else:
                    print("\nLock command " + result.text)
    finally:
        # Stop the subscription listening thread so we can quit
        controller.stop()


if __name__ == "__main__":
    main()
