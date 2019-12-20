#!/usr/bin/env python
"""Example script."""

# Parse Arguments
# Import project path
import argparse
import os
import sys
import time

# Import pyvera
from pyvera import VeraController, VeraDevice


# Define a callback that runs each time a device changes state
def device_info_callback(vera_device: VeraDevice) -> None:
    """Print device info."""
    # Do what we want with the changed device information
    print(
        "{}_{} values: {}".format(
            vera_device.name, vera_device.device_id, vera_device.get_all_values()
        )
    )
    print(
        "{}_{} alerts: {}".format(
            vera_device.name, vera_device.device_id, vera_device.get_alerts()
        )
    )


def main() -> None:
    """Run main code entrypoint."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))

    parser = argparse.ArgumentParser(description="device-listener")
    parser.add_argument(
        "-u", "--url", help="Vera URL, e.g. http://192.168.1.161:3480", required=True
    )
    group = parser.add_mutually_exclusive_group(required=True)
    # Pass in either the vera id of the device or the name
    group.add_argument(
        "-i", "--id", type=int, help="The Vera Device ID for subscription"
    )
    group.add_argument(
        "-n", "--name", help="The Vera Device name string for subscription"
    )
    args = parser.parse_args()

    # Start the controller
    controller = VeraController(args.url)
    controller.start()

    try:
        # Get the requested device on the vera controller
        found_device = None
        if args.name is not None:
            found_device = controller.get_device_by_name(args.name)
        elif args.id is not None:
            found_device = controller.get_device_by_id(args.id)

        if found_device is None:
            raise Exception(
                "Did not find  device with {} or {}".format(args.name, args.id)
            )

        print(
            "Listening for changes to {}: {}_{}".format(
                type(found_device).__name__, found_device.name, found_device.device_id
            )
        )

        # Register a callback that runs when the info for that device is updated
        controller.register(found_device, device_info_callback)
        print("Initial values: {}".format(found_device.get_all_values()))
        print("Initial alerts: {}".format(found_device.get_alerts()))

        # Loop until someone hits Ctrl-C to interrupt the listener
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Got interrupted by user")

        # Unregister our callback
        controller.unregister(found_device, device_info_callback)

    finally:
        # Stop the subscription listening thread so we can quit
        controller.stop()


if __name__ == "__main__":
    main()
