"""Namespace-local proof: this process starts only after firewall.sh succeeds."""
import json
import signal
import socket
import time


def stop(_signum, _frame):
    raise SystemExit(0)


signal.signal(signal.SIGTERM, stop)
with socket.socket() as listener:
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', 8001))
    ready_ns = time.time_ns()
    listener.listen(32)
    print(json.dumps({'event': 'egress_firewall_ready', 'time_ns': ready_ns}), flush=True)
    while True:
        connection, _ = listener.accept()
        connection.close()
