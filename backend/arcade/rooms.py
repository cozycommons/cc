"""Arcade rooms and a bounded WebSocket relay for live head-to-head games.

The protocol is documented in docs/cozy-arcade.md ("Rooms and relay"). Rooms are
in-memory and owned by this process: correctness assumes one API process, which
is how the backend runs today. Every hub mutation happens on the event loop
without an await in between, so no locks are needed.
"""
import asyncio
import base64
import binascii
import hmac
import json
import secrets
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, WebSocket
from starlette.concurrency import run_in_threadpool

from .store import Store

router = APIRouter()


@dataclass(frozen=True)
class Limits:
    capacity_max: int = 4
    frame_bytes: int = 8192
    payload_bytes: int = 4096
    rate_per_s: float = 60.0
    burst: int = 120
    pending_messages: int = 1024
    outbox: int = 256
    snapshot_keys: int = 8
    grace_s: float = 30.0
    hello_s: float = 5.0
    idle_s: float = 120.0
    rooms: int = 500
    rooms_per_user: int = 4
    sockets_per_user: int = 8


class RoomError(Exception):
    def __init__(self, code: str, **detail):
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(eq=False)
class Member:
    id: str
    session_id: str
    user_id: str
    ready: bool = False
    socket: "Connection | None" = None
    sent: int = 0  # last reliable seq accepted from this member
    # Reliable messages from other members that this member has not acknowledged.
    pending: dict[str, deque] = field(default_factory=dict)
    pending_count: int = 0
    expiry: asyncio.TimerHandle | None = None


@dataclass(eq=False)
class Room:
    id: str
    invite: str
    capacity: int
    members: dict[str, Member] = field(default_factory=dict)
    match: int = 0
    snapshots: dict[tuple[str, str], str] = field(default_factory=dict)


class Connection:
    """One authenticated socket. Its member survives the socket for the grace period."""

    def __init__(self, hub: "RoomHub", websocket: WebSocket):
        self.hub = hub
        self.websocket = websocket
        self.session: dict | None = None
        self.room: Room | None = None
        self.member: Member | None = None
        self.outbox: asyncio.Queue = asyncio.Queue()
        self.closed = False
        self.gone = False  # the peer disconnected; no close frame to send
        self.counted = False
        self.tokens = float(hub.limits.burst)
        self.refilled = time.monotonic()

    def send(self, message: dict):
        if self.closed:
            return
        if self.outbox.qsize() >= self.hub.limits.outbox:
            # A slow reader loses its socket, not its messages: they stay pending for resume.
            self.close(4503, "slow consumer")
            return
        self.outbox.put_nowait(json.dumps(message, separators=(",", ":")))

    def close(self, code: int, reason: str):
        if self.closed:
            return
        self.closed = True
        while not self.outbox.empty():
            self.outbox.get_nowait()
        self.outbox.put_nowait((code, reason))

    def take_token(self) -> bool:
        now = time.monotonic()
        limits = self.hub.limits
        self.tokens = min(limits.burst, self.tokens + (now - self.refilled) * limits.rate_per_s)
        self.refilled = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True

    async def write(self):
        while True:
            item = await self.outbox.get()
            if isinstance(item, tuple):
                with suppress(Exception):
                    await self.websocket.close(*item)
                return
            await self.websocket.send_text(item)

    async def receive_text(self, timeout: float) -> str | None:
        """The next text frame, or None after a disconnect or a protocol close."""
        try:
            message = await asyncio.wait_for(self.websocket.receive(), timeout)
        except asyncio.TimeoutError:
            self.close(4408, "idle")
            return None
        if message["type"] == "websocket.disconnect":
            self.closed = self.gone = True
            return None
        text = message.get("text")
        if text is None:
            self.close(4400, "text frames only")
            return None
        if len(text.encode()) > self.hub.limits.frame_bytes:
            self.close(4413, "frame too large")
            return None
        if not self.take_token():
            self.close(4429, "rate limit")
            return None
        return text

    async def read(self, authenticate):
        limits = self.hub.limits
        hello = parse(await self.receive_text(limits.hello_s))
        token = hello.get("session") if hello and hello.get("t") == "hello" else None
        session = await authenticate(token) if isinstance(token, str) and len(token) <= 256 else None
        if self.closed:
            return
        if not session:
            self.close(4401, "launch session required")
            return
        self.session = {"id": str(session["id"]), "user_id": str(session["user_id"])}
        if not self.hub.add_socket(self):
            self.close(4429, "too many sockets")
            return
        self.send({"t": "hello", "limits": {
            "payload_bytes": limits.payload_bytes, "rate_per_s": limits.rate_per_s, "burst": limits.burst,
            "idle_s": limits.idle_s, "grace_s": limits.grace_s, "capacity_max": limits.capacity_max}})
        while not self.closed:
            text = await self.receive_text(limits.idle_s)
            if text is None:
                return
            message = parse(text)
            if message is None:
                self.close(4400, "invalid envelope")
                return
            self.hub.handle(self, message)

    async def run(self, authenticate):
        writer = asyncio.create_task(self.write())
        reader = asyncio.create_task(self.read(authenticate))
        failed = False
        try:
            await asyncio.wait({reader, writer}, return_when=asyncio.FIRST_COMPLETED)
            failed = reader.done() and not reader.cancelled() and reader.exception() is not None
            if not self.gone and not writer.done():
                # No-op when a protocol close is already queued.
                if failed:
                    self.close(1011, "server error")
                else:
                    self.close(1000, "")
                # Give the close frame a moment; a stalled peer must not hold the task.
                await asyncio.wait({writer}, timeout=2)
        finally:
            for task in (reader, writer):
                task.cancel()
            self.closed = True
            self.hub.detach(self)
        if failed:
            reader.result()  # re-raise so the server logs it, e.g. a failed session lookup


def parse(text: str | None) -> dict | None:
    if text is None:
        return None
    try:
        message = json.loads(text)
    except ValueError:
        return None
    return message if isinstance(message, dict) and isinstance(message.get("t"), str) else None


class RoomHub:
    def __init__(self, limits: Limits | None = None):
        self.limits = limits or Limits()
        self.rooms: dict[str, Room] = {}
        self.sockets: dict[str, int] = {}

    # Socket lifecycle

    def add_socket(self, conn: Connection) -> bool:
        user = conn.session["user_id"]
        if self.sockets.get(user, 0) >= self.limits.sockets_per_user:
            return False
        self.sockets[user] = self.sockets.get(user, 0) + 1
        conn.counted = True
        return True

    def detach(self, conn: Connection):
        if conn.counted:
            conn.counted = False
            user = conn.session["user_id"]
            self.sockets[user] -= 1
            if not self.sockets[user]:
                del self.sockets[user]
        member, room = conn.member, conn.room
        conn.member = conn.room = None
        if not member or member.socket is not conn:
            return
        member.socket = None
        member.ready = False
        member.expiry = asyncio.get_running_loop().call_later(
            self.limits.grace_s, self._expire, room, member)
        self._broadcast_state(room)

    def _expire(self, room: Room, member: Member):
        if member.socket is None and room.members.get(member.id) is member:
            self._remove(room, member)

    # Dispatch

    def handle(self, conn: Connection, message: dict):
        if message["t"] == "ping":
            conn.send({"t": "pong"})
            return
        handler = {
            "room.create": self._create, "room.join": self._join, "room.ready": self._ready,
            "room.leave": self._leave, "room.state": self._state, "room.send": self._send,
            "ack": self._ack,
        }.get(message["t"])
        if handler is None:
            conn.close(4400, "unknown message type")
            return
        op = message.get("id")
        op = op if isinstance(op, str) and len(op) <= 64 else None
        try:
            handler(conn, message, op)
        except RoomError as error:
            conn.send({"t": "error", "id": op, "code": error.code, **error.detail})

    def _member(self, conn: Connection) -> tuple[Room, Member]:
        if not conn.member:
            raise RoomError("not_member")
        return conn.room, conn.member

    def _check_user_rooms(self, user_id: str):
        count = sum(1 for room in self.rooms.values()
                    for member in room.members.values() if member.user_id == user_id)
        if count >= self.limits.rooms_per_user:
            raise RoomError("too_many_rooms")

    def _create(self, conn: Connection, message: dict, op: str | None):
        if conn.member:
            raise RoomError("already_in_room")
        capacity = message.get("capacity", 2)
        if type(capacity) is not int or not 2 <= capacity <= self.limits.capacity_max:
            raise RoomError("bad_request")
        if len(self.rooms) >= self.limits.rooms:
            raise RoomError("busy")
        self._check_user_rooms(conn.session["user_id"])
        room = Room(id=secrets.token_urlsafe(9), invite=secrets.token_urlsafe(18), capacity=capacity)
        self.rooms[room.id] = room
        self._admit(conn, room, op)

    def _join(self, conn: Connection, message: dict, op: str | None):
        room = self.rooms.get(message.get("room")) if isinstance(message.get("room"), str) else None
        invite = message.get("invite")
        # One error for a missing room and a wrong invite, so room ids reveal nothing.
        if not room or not isinstance(invite, str) or not hmac.compare_digest(invite.encode(), room.invite.encode()):
            raise RoomError("not_found")
        existing = next((m for m in room.members.values() if m.session_id == conn.session["id"]), None)
        if conn.member and conn.member is not existing:
            raise RoomError("already_in_room")
        if existing:
            self._attach(conn, room, existing, op)
            return
        if len(room.members) >= room.capacity:
            raise RoomError("room_full")
        self._check_user_rooms(conn.session["user_id"])
        self._admit(conn, room, op)

    def _admit(self, conn: Connection, room: Room, op: str | None):
        member = Member(id=secrets.token_urlsafe(6), session_id=conn.session["id"],
                        user_id=conn.session["user_id"])
        room.members[member.id] = member
        self._attach(conn, room, member, op)

    def _attach(self, conn: Connection, room: Room, member: Member, op: str | None):
        if member.expiry:
            member.expiry.cancel()
            member.expiry = None
        previous = member.socket
        if previous and previous is not conn:
            previous.member = previous.room = None
            previous.close(4409, "replaced by a newer connection")
        member.socket = conn
        conn.room, conn.member = room, member
        conn.send({"t": "room.joined", "id": op, "room": room.id, "invite": room.invite,
                   "you": member.id, "sent": member.sent})
        # Resume: everything unacknowledged, then the latest snapshot of each sender.
        for sender, queued in member.pending.items():
            for seq, data in queued:
                conn.send({"t": "room.message", "from": sender, "seq": seq, "data": data})
        for (sender, key), data in room.snapshots.items():
            if sender != member.id:
                conn.send({"t": "room.message", "from": sender, "snapshot": key, "data": data})
        self._broadcast_state(room)

    def _ready(self, conn: Connection, message: dict, op: str | None):
        room, member = self._member(conn)
        member.ready = message.get("ready", True) is True
        self._broadcast_state(room)
        members = room.members.values()
        if len(room.members) == room.capacity and all(m.ready and m.socket for m in members):
            room.match += 1
            seed = secrets.randbits(31)
            for each in members:
                each.ready = False
                each.socket.send({"t": "room.start", "match": room.match, "seed": seed})
            self._broadcast_state(room)

    def _leave(self, conn: Connection, message: dict, op: str | None):
        room, member = self._member(conn)
        conn.room = conn.member = None
        member.socket = None
        self._remove(room, member)
        conn.send({"t": "room.left", "id": op, "room": room.id})

    def _state(self, conn: Connection, message: dict, op: str | None):
        room, member = self._member(conn)
        conn.send({**self._state_for(room, member), "id": op})

    def _send(self, conn: Connection, message: dict, op: str | None):
        room, member = self._member(conn)
        data = message.get("data")
        if not isinstance(data, str):
            raise RoomError("bad_request")
        try:
            size = len(base64.b64decode(data, validate=True))
        except (binascii.Error, ValueError):
            raise RoomError("bad_request") from None
        if size > self.limits.payload_bytes:
            raise RoomError("payload_too_large", limit=self.limits.payload_bytes)
        others = [m for m in room.members.values() if m is not member]
        if "snapshot" in message:
            key = message["snapshot"]
            if not isinstance(key, str) or not 0 < len(key) <= 32:
                raise RoomError("bad_request")
            mine = sum(1 for sender, _ in room.snapshots if sender == member.id)
            if (member.id, key) not in room.snapshots and mine >= self.limits.snapshot_keys:
                raise RoomError("too_many_snapshots")
            room.snapshots[(member.id, key)] = data
            for other in others:
                if other.socket:
                    other.socket.send({"t": "room.message", "from": member.id, "snapshot": key, "data": data})
            return
        seq = message.get("seq")
        if type(seq) is not int or seq < 1:
            raise RoomError("bad_request")
        if seq <= member.sent:
            conn.send({"t": "ack", "seq": member.sent})  # duplicate: acknowledge, never relay twice
            return
        if seq != member.sent + 1:
            raise RoomError("seq_gap", expected=member.sent + 1)
        member.sent = seq
        for other in others:
            other.pending.setdefault(member.id, deque()).append((seq, data))
            other.pending_count += 1
            if other.pending_count > self.limits.pending_messages:
                self._drop(room, other)
            elif other.socket:
                other.socket.send({"t": "room.message", "from": member.id, "seq": seq, "data": data})
        conn.send({"t": "ack", "seq": seq})

    def _ack(self, conn: Connection, message: dict, op: str | None):
        _, member = self._member(conn)
        seq = message.get("seq")
        queued = member.pending.get(message.get("from")) if isinstance(message.get("from"), str) else None
        if type(seq) is not int or queued is None:
            return
        while queued and queued[0][0] <= seq:
            queued.popleft()
            member.pending_count -= 1

    # Membership changes

    def _drop(self, room: Room, member: Member):
        """A member that cannot keep up would break the reliable stream; remove it."""
        socket = member.socket
        member.socket = None
        self._remove(room, member)
        if socket:
            socket.room = socket.member = None
            socket.close(4503, "too far behind")

    def _remove(self, room: Room, member: Member):
        if member.expiry:
            member.expiry.cancel()
        room.members.pop(member.id, None)
        for key in [key for key in room.snapshots if key[0] == member.id]:
            del room.snapshots[key]
        if not room.members:
            self.rooms.pop(room.id, None)
        else:
            self._broadcast_state(room)

    def _state_for(self, room: Room, member: Member) -> dict:
        return {"t": "room.state", "room": room.id, "capacity": room.capacity, "match": room.match,
                "you": member.id, "members": [
                    {"id": m.id, "ready": m.ready, "connected": m.socket is not None}
                    for m in room.members.values()]}

    def _broadcast_state(self, room: Room):
        for member in room.members.values():
            if member.socket:
                member.socket.send(self._state_for(room, member))


def sessions(websocket: WebSocket) -> Store:
    return Store(websocket.app.state.mcp_supabase)


@router.websocket("/rooms/socket")
async def room_socket(websocket: WebSocket, state=Depends(sessions)):
    hub = getattr(websocket.app.state, "arcade_rooms", None)
    if hub is None:
        await websocket.close(4404)  # before accept: the handshake is refused
        return
    await websocket.accept()

    async def authenticate(token: str):
        # The launch capability, never the Commons bearer, identifies the member.
        return await run_in_threadpool(state.session, token)

    await Connection(hub, websocket).run(authenticate)
