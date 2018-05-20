# PyVera
A simple Python library to control devices via the Vera controller (http://getvera.com/).

Based on https://github.com/jamespcole/home-assistant-vera-api

Additions to support subscriptions and some additional devices

How to use
----------


    >>> import pyvera

    >>> controller = pyvera.VeraController("http://192.168.1.161:3480/")
    >>> devices = controller.get_devices('On/Off Switch')
    >>> devices
    [VeraSwitch (id=15 category=On/Off Switch name=Bookcase Uplighters), VeraSwitch (id=16 category=On/Off Switch name=Bookcase device)]

    >>> devices[1]
    VeraSwitch (id=15 category=On/Off Switch name=Bookcase Uplighters)

    >>> devices[1].is_switched_on()
    False

    >>> devices[1].switch_on()
    >>> devices[1].is_switched_on()
    True

    >>> devices[1].switch_off()

Debugging
-------
You may use the PYVERA_LOGLEVEL environment variable to output more verbose messages to the console.  For instance, to show all debug level messages using the list-devices implementation in the example directory, run something similar to:
~~~~
$ PYVERA_LOGLEVEL=DEBUG ./examples/list-devices.py -u http://192.168.1.l61:3480
~~~~

License
-------
The initial code was initially was written by James Cole and released under the BSD license. The rest is released under the MIT license.
