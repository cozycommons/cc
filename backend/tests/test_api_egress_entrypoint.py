import pytest

from api_egress_entrypoint import load_runtime


def test_runtime_loader_preserves_raw_secret_values(tmp_path):
    path = tmp_path / 'runtime'
    path.write_text('# Comment\nKEY=synthetic-$literal=with spaces\nEMPTY=\n')
    assert load_runtime(path) == {'KEY': 'synthetic-$literal=with spaces', 'EMPTY': ''}


@pytest.mark.parametrize('content', ['export KEY=secret', 'KEY=one\nKEY=two', 'malformed-secret-line'])
def test_runtime_loader_rejects_ambiguous_input(tmp_path, content):
    path = tmp_path / 'runtime'
    path.write_text(content)
    with pytest.raises(ValueError):
        load_runtime(path)


def test_gate_times_out_without_namespace_proof(monkeypatch):
    import api_egress_entrypoint as entrypoint
    monkeypatch.setattr(entrypoint, 'guard_ready', lambda _: False)
    with pytest.raises(RuntimeError, match='readiness timed out'):
        entrypoint.wait_for_guard(timeout=0)


def test_gate_rejects_working_direct_socket(monkeypatch):
    import socket
    import api_egress_entrypoint as entrypoint
    monkeypatch.setattr(entrypoint, 'guard_ready', lambda _: True)
    with socket.socket() as endpoint:
        endpoint.bind(('127.0.0.1', 0))
        endpoint.listen()
        create_connection = socket.create_connection
        monkeypatch.setattr(entrypoint.socket, 'create_connection', lambda _address, **kwargs: create_connection(endpoint.getsockname(), **kwargs))
        with pytest.raises(RuntimeError, match='direct internet'):
            entrypoint.wait_for_guard()


def test_gate_accepts_proof_only_when_direct_socket_is_blocked(monkeypatch):
    import api_egress_entrypoint as entrypoint
    monkeypatch.setattr(entrypoint, 'guard_ready', lambda _: True)

    def blocked(*args, **kwargs):
        raise OSError('blocked')

    monkeypatch.setattr(entrypoint.socket, 'create_connection', blocked)
    entrypoint.wait_for_guard()


def test_watchdog_stops_child_when_namespace_proof_disappears(tmp_path, monkeypatch):
    import os
    import sys
    import api_egress_entrypoint as entrypoint
    marker = tmp_path / 'pid'
    # Lose proof only after the real child has started, without assuming spawn timing.
    monkeypatch.setattr(entrypoint, 'guard_ready', lambda _: not marker.exists())
    code = f'from pathlib import Path; import os,time; Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(30)'
    assert entrypoint.supervise([sys.executable, '-c', code], interval=.2) == 1
    pid = int(marker.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_supervisor_preserves_child_exit_code():
    import sys
    import api_egress_entrypoint as entrypoint
    assert entrypoint.supervise([sys.executable, '-c', 'raise SystemExit(7)']) == 7
