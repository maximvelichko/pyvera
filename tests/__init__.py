import unittest
import mock
import json
import logging

import sys
import os
sys.path.insert(0, os.path.abspath('..'))
import pyvera

#pyvera.logger = mock.create_autospec(logging.Logger)
logging.basicConfig(level=logging.DEBUG)
pyvera.logger = logging.getLogger(__name__)

class TestVeraLock(unittest.TestCase):
    def test_set_lock_state(self):

        mock_controller = mock.create_autospec(pyvera.VeraController)
        status_json = json.loads(
                '{'
                '  "id": 33,'
                '  "deviceInfo": {'
                     # pyvera.CATEGORY_LOCK
                '    "category": 7,'
                '    "categoryName": "Doorlock",'
                '    "name": "MyTestDeadbolt",'
                '    "locked": 0'
                '  }'
                '}'
                )
        lock = pyvera.VeraLock(status_json, mock_controller)
        lock.set_lock_state(1)
        self.assertTrue(lock.get_value('locked'), '1')

if __name__ == '__main__':
    unittest.main()

