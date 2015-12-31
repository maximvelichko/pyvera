# pythonhome-vera
A simple Python library to control devices via the Vera controller.

Based on https://github.com/jamespcole/home-assistant-vera-api

Additions to support subscriptions and some additional devices

How to use
----------


    >>> import pyvera

    >>> controller = pyvera.VeraController("http://192.168.1.161:3480/")
    >>> devices = controller.get_devices('On/Off Switch')
    >>> devices
    [<pyvera.VeraSwitch object at 0x105ea8dd8>, <pyvera.VeraSwitch object at 0x105ea8c18>, <pyvera.VeraSwitch object at 0x105ea8b00>, <pyvera.VeraSwitch object at 0x105ea8c50>, <pyvera.VeraSwitch object at 0x105ea87b8>, <pyvera.VeraSwitch object at 0x105ea85f8>, <pyvera.VeraSwitch object at 0x105ea8ac8>, <pyvera.VeraSwitch object at 0x105ea86a0>, <pyvera.VeraSwitch object at 0x105ea86d8>, <pyvera.VeraSwitch object at 0x105f754a8>, <pyvera.VeraSwitch object at 0x105f753c8>, <pyvera.VeraSwitch object at 0x105f75400>, <pyvera.VeraSwitch object at 0x105f754e0>, <pyvera.VeraSwitch object at 0x105f75630>, <pyvera.VeraSwitch object at 0x105f915f8>]

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
The code in pywemo/ouimeaux_device is written by James Cole
