#!/usr/bin/env python3
"""Loopback-only /rest/v1 adapter for the real PostgreSQL/PostgREST CI service."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", default="http://127.0.0.1:55433")
    args = parser.parse_args()
    # The upstream is explicitly provided by the test environment, never a request.
    origin = urlparse(args.upstream)
    if origin.scheme != "http" or origin.path not in {"","/"} or origin.username or origin.password:
        parser.error("Expected a test-service HTTP origin")
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def dispatch(self):
            if not self.path.startswith("/rest/v1/"):
                self.send_error(404)
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", "0"))) or None
            headers = {k:v for k,v in self.headers.items() if k.lower() in {"authorization","content-type","prefer","accept","range","accept-profile","content-profile"}}
            request = Request(args.upstream + self.path[len("/rest/v1"):], method=self.command, data=body, headers=headers)
            try:
                response = urlopen(request, timeout=30)
            except HTTPError as error:
                response = error
            payload = response.read()
            self.send_response(response.code)
            for k,v in response.headers.items():
                if k.lower() in {"content-type","content-range","location","preference-applied"}: self.send_header(k,v)
            self.send_header("Content-Length",str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        do_GET = do_POST = do_PATCH = do_DELETE = do_HEAD = dispatch
    ThreadingHTTPServer(("127.0.0.1",55431),Handler).serve_forever()

if __name__ == "__main__":
    main()
