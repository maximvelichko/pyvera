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
    [<pyvera.VeraSwitch object at 0x105ea8dd8>, <pyvera.VeraSwitch object at 0x105ea8c18>]

    >>> devices[0]
    <pyvera.VeraSwitch object at 0x105ea8dd8>

    >>> devices[1].name
    'Bookcase Uplighters'

    >>> devices[1].is_switched_on()
    False

    >>> devices[1].switch_on()
    >>> devices[1].is_switched_on()
    True

    >>> devices[1].switch_off()

License
-------
The initial code was initially was written by James Cole and released under the BSD license. The rest is released under the MIT license.
