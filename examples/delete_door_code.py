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
    parser.add_argument("-i", "--id", help='Device ID: "123"', required=True)
    args = parser.parse_args()

    # Start the controller
    controller = VeraController(args.url)
    controller.start()

    try:
        device = controller.get_device_by_id(int(args.id))

        if isinstance(device, VeraLock):
            pins = device.get_pin_codes()
            found_slot = None
            for slot, name, _ in pins:
                if name == args.name:
                    found_slot = slot
            if found_slot is None:
                print("No matching slot found\n")
                return
            result = device.clear_slot_pin(slot=int(found_slot))
            if result.status_code == 200:
                print(
                    "\nCommand succesfully sent to Lock \
                \nWait for the lock to process the request"
                )
            else:
                print("\nLock command " + result.text)

    finally:
        # Stop the subscription listening thread so we can quit
        controller.stop()


if __name__ == "__main__":
    main()
