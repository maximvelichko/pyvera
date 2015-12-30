"""Module to listen for vera events."""
import collections
import functools
import logging
import sched
import socket
import time
import threading

from cgi import parse_header, parse_multipart
from xml.etree import cElementTree

try:
    import BaseHTTPServer
    from urlparse import parse_qs
except ImportError:
    import http.server as BaseHTTPServer
    from urllib.parse import parse_qs

import requests

LOG = logging.getLogger(__name__)
SUCCESS = '<html><body><h1>200 OK</h1></body></html>'
PORT = 8990


class RequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):

    def do_POST(self):
        outer = self.server.outer
        # CITATION: http://stackoverflow.com/questions/4233218/python-basehttprequesthandler-post-variables
        ctype, pdict = parse_header(self.headers['content-type'])
        if ctype == 'multipart/form-data':
            postvars = parse_multipart(self.rfile, pdict)
        elif ctype == 'application/x-www-form-urlencoded':
            length = int(self.headers['content-length'])
            postvars = parse_qs(
                    self.rfile.read(length),
                    keep_blank_values=1)
        else:
            postvars = {}

        postvars = {k.decode('utf8'): [v.decode('UTF8') for v in l] for k, l in postvars.items()}
        devices = [outer._devices.get(int(id)) for id in postvars.get('device_id', [])]

        outer._event(devices)

        # Tell the browser everything is okay and that there is
        # HTML to display.
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', len(SUCCESS))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(SUCCESS.encode("UTF-8"))

    def log_message(self, format, *args):
      LOG.info(format, *args)


class SubscriptionRegistry(object):
    """Class for subscribing to wemo events."""

    def __init__(self):
        self._devices = {}
        self._callbacks = collections.defaultdict(list)
        self._exiting = False

        self._http_thread = None
        self._httpd = None

    def register(self, device):
        if not device:
            LOG.error("Received an invalid device: %r", device)
            return

        LOG.info("Subscribing to events for %s", device.name)
        # Provide a function to register a callback when the device changes
        # state
        device.register_listener = functools.partial(self.on, device, None)
        self._devices[device.vera_device_id] = device

    def _event(self, devices):
        LOG.info("Got vera event for devices %s", [d.name for d in devices])
        # if not devices specified - callback everything
        if devices:
            for device in devices:
                for callback in self._callbacks.get(device, ()):
                    callback(device)
        else:
            for device, callbacks in self._callbacks.items():
                for callback in callbacks:
                    callback(device)



    def on(self, device, callback):
        self._callbacks[device].append((callback))

    def start(self):
        self._http_thread = threading.Thread(target=self._run_http_server,
                                             name='Vera HTTP Thread')
        self._http_thread.deamon = True
        self._http_thread.start()

    def stop(self):
        self._httpd.shutdown()

    def join(self):
        self._http_thread.join()

    def _run_http_server(self):
        self._httpd = BaseHTTPServer.HTTPServer(('', PORT), RequestHandler)
        self._httpd.allow_reuse_address = True
        self._httpd.outer = self
        LOG.info("Vera listening on port %d", PORT)
        self._httpd.serve_forever()

