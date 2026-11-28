"""Rooms and relay: two clients per room, reliable stream, limits, isolation, resume."""
import base64
import time
from contextlib import suppress

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from arcade.rooms import Limits, RoomHub, router, sessions


class Sessions:
    """Launch capabilities: token -> session row, as Store.session returns it."""
    def __init__(self):
        self.rows = {f"token-{name}": {"id": f"launch-{name}", "user_id": f"user-{name}"}
                     for name in ("a", "b", "c", "d")}

    def session(self, token):
        if token == "token-outage":
            raise ConnectionError("database unavailable")
        return self.rows.get(token)


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


@pytest.fixture
def make_client():
    clients = []

    def make(hub: RoomHub | None = None):
        app = FastAPI()
        app.include_router(router, prefix="/arcade")
        app.dependency_overrides[sessions] = Sessions
        app.state.arcade_rooms = hub
        client = TestClient(app)
        client.__enter__()  # one event loop for every socket, as in the real server
        client.open_sockets = []
        clients.append(client)
        return client

    yield make
    for client in clients:
        for ws in client.open_sockets:  # the portal cannot exit while a socket task runs
            with suppress(Exception):
                ws.__exit__(None, None, None)
        client.__exit__(None, None, None)


def connect(client, name):
    ws = client.websocket_connect("/arcade/rooms/socket")
    socket = ws.__enter__()
    client.open_sockets.append(ws)
    socket.send_json({"t": "hello", "session": f"token-{name}"})
    assert socket.receive_json()["t"] == "hello"
    return socket


def expect(socket, kind):
    """Skip room.state broadcasts until the wanted message type."""
    while True:
        message = socket.receive_json()
        if message["t"] == kind:
            return message
        assert message["t"] == "room.state", message


def pair(client, a="a", b="b"):
    first = connect(client, a)
    first.send_json({"t": "room.create", "id": "op1"})
    created = expect(first, "room.joined")
    second = connect(client, b)
    second.send_json({"t": "room.join", "room": created["room"], "invite": created["invite"]})
    joined = expect(second, "room.joined")
    return first, second, created, joined


def quiet(socket):
    """Prove nothing else is queued: the pong must be next after any state broadcasts."""
    socket.send_json({"t": "ping"})
    expect(socket, "pong")


def test_disabled_relay_refuses_handshake(make_client):
    client = make_client(None)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/arcade/rooms/socket") as socket:
            socket.receive_json()


def test_launch_session_required(make_client):
    client = make_client(RoomHub())
    with client.websocket_connect("/arcade/rooms/socket") as socket:
        socket.send_json({"t": "hello", "session": "commons-bearer"})
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
    assert closed.value.code == 4401


def test_session_lookup_failure_closes_as_server_error(make_client):
    client = make_client(RoomHub())
    with pytest.raises(ConnectionError):  # re-raised for the server log
        with client.websocket_connect("/arcade/rooms/socket") as socket:
            socket.send_json({"t": "hello", "session": "token-outage"})
            with pytest.raises(WebSocketDisconnect) as closed:
                socket.receive_json()
    assert closed.value.code == 1011


def test_two_clients_play_a_match_and_exchange_a_reliable_stream(make_client):
    client = make_client(RoomHub())
    a, b, created, joined = pair(client)
    assert created["you"] != joined["you"] and joined["sent"] == 0

    a.send_json({"t": "room.ready"})
    b.send_json({"t": "room.ready"})
    start_a, start_b = expect(a, "room.start"), expect(b, "room.start")
    assert start_a == start_b and start_a["match"] == 1
    state = expect(a, "room.state")
    assert [m["ready"] for m in state["members"]] == [False, False]  # ready resets per match

    a.send_json({"t": "room.send", "seq": 1, "data": b64(b"\x01bag-seed")})
    assert expect(a, "ack") == {"t": "ack", "seq": 1}
    message = expect(b, "room.message")
    assert message == {"t": "room.message", "from": created["you"], "seq": 1, "data": b64(b"\x01bag-seed")}

    a.send_json({"t": "room.send", "seq": 1, "data": b64(b"retry")})  # retransmit after a lost ack
    assert expect(a, "ack") == {"t": "ack", "seq": 1}
    a.send_json({"t": "room.send", "seq": 3, "data": b64(b"skipped")})
    assert expect(a, "error")["expected"] == 2
    a.send_json({"t": "room.send", "seq": 2, "data": b64(b"\x02lockdown")})
    expect(a, "ack")
    assert expect(b, "room.message")["seq"] == 2  # the duplicate was never relayed

    b.send_json({"t": "room.send", "snapshot": "board", "data": b64(b"old")})
    b.send_json({"t": "room.send", "snapshot": "board", "data": b64(b"new")})
    assert expect(a, "room.message")["snapshot"] == "board"
    assert expect(a, "room.message")["data"] == b64(b"new")
    quiet(b)


def test_rooms_are_isolated_and_membership_is_checked(make_client):
    client = make_client(RoomHub())
    a, b, first, _ = pair(client, "a", "b")
    c, d, second, _ = pair(client, "c", "d")

    a.send_json({"t": "room.send", "seq": 1, "data": b64(b"for b only")})
    expect(a, "ack")
    assert expect(b, "room.message")["data"] == b64(b"for b only")
    quiet(c)
    quiet(d)

    c.send_json({"t": "room.join", "room": first["room"], "invite": first["invite"]})
    assert expect(c, "error")["code"] == "already_in_room"
    outsider = connect(client, "a")  # a second launch is not yet a member of anything
    outsider.send_json({"t": "room.send", "seq": 1, "data": b64(b"x")})
    assert expect(outsider, "error")["code"] == "not_member"
    outsider.send_json({"t": "room.join", "room": first["room"], "invite": second["invite"]})
    assert expect(outsider, "error")["code"] == "not_found"


def test_room_full_and_payload_and_rate_limits(make_client):
    client = make_client(RoomHub(Limits(payload_bytes=8, burst=20, rate_per_s=0.001)))
    a, b, created, _ = pair(client)
    c = connect(client, "c")
    c.send_json({"t": "room.join", "room": created["room"], "invite": created["invite"]})
    assert expect(c, "error")["code"] == "room_full"

    a.send_json({"t": "room.send", "seq": 1, "data": b64(b"123456789")})
    assert expect(a, "error") == {"t": "error", "id": None, "code": "payload_too_large", "limit": 8}
    a.send_json({"t": "room.send", "seq": 1, "data": "not base64!"})
    assert expect(a, "error")["code"] == "bad_request"

    with pytest.raises(WebSocketDisconnect) as closed:
        for _ in range(30):
            a.send_json({"t": "ping"})
        while True:
            a.receive_json()
    assert closed.value.code == 4429


def test_oversized_frame_closes_socket(make_client):
    client = make_client(RoomHub(Limits(frame_bytes=64)))
    socket = connect(client, "a")
    socket.send_text('{"t":"ping","pad":"' + "x" * 100 + '"}')
    with pytest.raises(WebSocketDisconnect) as closed:
        socket.receive_json()
    assert closed.value.code == 4413


def test_reconnect_replays_unacknowledged_messages(make_client):
    client = make_client(RoomHub())
    a, b, created, joined = pair(client)
    a.send_json({"t": "room.send", "seq": 1, "data": b64(b"one")})
    expect(a, "ack")
    expect(b, "room.message")
    b.send_json({"t": "ack", "from": created["you"], "seq": 1})
    b.close()
    assert expect(a, "room.state")["members"][1]["connected"] is False

    a.send_json({"t": "room.send", "seq": 2, "data": b64(b"two")})
    expect(a, "ack")
    a.send_json({"t": "room.send", "snapshot": "board", "data": b64(b"latest")})

    again = connect(client, "b")
    again.send_json({"t": "room.join", "room": created["room"], "invite": created["invite"]})
    resumed = expect(again, "room.joined")
    assert resumed["you"] == joined["you"]
    replay = expect(again, "room.message")
    assert (replay["seq"], replay["data"]) == (2, b64(b"two"))  # acknowledged seq 1 is not replayed
    assert expect(again, "room.message")["snapshot"] == "board"
    assert expect(a, "room.state")["members"][1]["connected"] is True


def test_newer_connection_replaces_older(make_client):
    client = make_client(RoomHub())
    a, b, created, _ = pair(client)
    again = connect(client, "b")
    again.send_json({"t": "room.join", "room": created["room"], "invite": created["invite"]})
    expect(again, "room.joined")
    with pytest.raises(WebSocketDisconnect) as closed:
        while True:
            b.receive_json()
    assert closed.value.code == 4409


def test_grace_expiry_and_lagging_member_leave_the_room(make_client):
    client = make_client(RoomHub(Limits(grace_s=0.2, pending_messages=3)))
    a, b, created, _ = pair(client)
    b.close()
    expect(a, "room.state")
    for seq in range(1, 5):  # b is offline and cannot acknowledge
        a.send_json({"t": "room.send", "seq": seq, "data": b64(b"x")})
        expect(a, "ack")
    a.send_json({"t": "room.state", "id": "dropped"})
    assert len(expect_reply(a, "dropped")["members"]) == 1

    c = connect(client, "c")
    c.send_json({"t": "room.join", "room": created["room"], "invite": created["invite"]})
    expect(c, "room.joined")
    c.close()
    expect(a, "room.state")
    time.sleep(0.4)
    a.send_json({"t": "room.state", "id": "s"})
    assert len(expect_reply(a, "s")["members"]) == 1


def expect_reply(socket, op):
    while True:
        message = socket.receive_json()
        if message.get("id") == op:
            return message


def test_leave_removes_member_and_empty_room(make_client):
    hub = RoomHub()
    client = make_client(hub)
    a, b, created, _ = pair(client)
    b.send_json({"t": "room.leave", "id": "bye"})
    assert expect(b, "room.left")["id"] == "bye"
    assert len(expect(a, "room.state")["members"]) == 1
    a.send_json({"t": "room.leave"})
    expect(a, "room.left")
    assert hub.rooms == {}
