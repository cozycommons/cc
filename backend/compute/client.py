"""HTTP transport shared by producers and workers."""
from urllib.parse import urlsplit

import httpx


class Client:
    def __init__(self, url, token, transport=None):
        parts = urlsplit(url)
        if parts.scheme != 'https' and not (parts.scheme == 'http' and parts.hostname in ('127.0.0.1', 'localhost', '::1')):
            raise ValueError('Compute requires HTTPS outside loopback')
        if not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError('Invalid compute URL')
        self.url, self.token, self.transport = url.rstrip('/'), token, transport

    def call(self, path, body=None):
        with httpx.Client(timeout=20, follow_redirects=False, transport=self.transport) as client:
            response = client.request('GET' if body is None else 'POST', self.url + '/compute/' + path,
                                      json=body, headers={'Authorization': 'Bearer ' + self.token})
            response.raise_for_status()
            return response.json()

    def submit(self, kind, payload, idempotency_key=None):
        return self.call('jobs', {'type': kind, 'payload': payload, 'idempotency_key': idempotency_key})

    def status(self, identifier):
        return self.call('jobs/' + identifier)
