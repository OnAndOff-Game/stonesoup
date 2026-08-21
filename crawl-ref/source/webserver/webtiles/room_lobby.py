"""Dedicated lobby and P2P signalling rules for cooperative Crawl rooms.

The dedicated WebTiles server owns identities, the public room directory and
room membership.  Gameplay peers use WebRTC; the server only validates and
relays the offer/answer/ICE signalling envelopes needed to establish those
connections.
"""

from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
import json
import re
import secrets
import time
from typing import Dict, Mapping, Optional


class RoomLobbyError(ValueError):
    """Raised when a client requests an invalid room operation."""


class RoomState(str, Enum):
    WAITING = "waiting"
    RUNNING = "running"


class RoomRole(str, Enum):
    PLAYER = "player"
    SPECTATOR = "spectator"


DEFAULT_WORLD_SETTINGS = {
    # These values deliberately produce an unmodified, normal Crawl world.
    "game_mode": "standard",
    "seed": "",
    # Multiplayer-layer settings; they do not alter Crawl's world generation.
    "turn_seconds": 15,
    "transition_seconds": 10,
    "max_players": 4,
}

GAME_MODES = ("standard", "seeded", "descent", "sprint")
MAX_SIGNAL_BYTES = 64 * 1024
_SPACE_RE = re.compile(r"\s+")


def _clean_text(value, label, minimum, maximum):
    if not isinstance(value, str):
        raise RoomLobbyError("%s은(는) 문자열이어야 합니다" % label)
    value = _SPACE_RE.sub(" ", value.strip())
    if len(value) < minimum or len(value) > maximum:
        raise RoomLobbyError(
            "%s은(는) %d자에서 %d자 사이여야 합니다" %
            (label, minimum, maximum))
    return value


def normalize_display_name(value):
    return _clean_text(value, "닉네임", 2, 20)


def normalize_room_title(value):
    return _clean_text(value, "방 제목", 1, 40)


def normalize_world_settings(settings=None):
    """Return a validated settings dict with vanilla Crawl defaults."""

    if settings is None:
        settings = {}
    if not isinstance(settings, Mapping):
        raise RoomLobbyError("월드 설정은 객체 형식이어야 합니다")

    unknown = set(settings) - set(DEFAULT_WORLD_SETTINGS)
    if unknown:
        raise RoomLobbyError("알 수 없는 월드 설정입니다: %s" %
                             ", ".join(sorted(unknown)))

    result = dict(DEFAULT_WORLD_SETTINGS)
    result.update(settings)

    mode = result["game_mode"]
    if mode not in GAME_MODES:
        raise RoomLobbyError("지원하지 않는 게임 모드입니다")

    seed = result["seed"]
    if seed is None:
        seed = ""
    if not isinstance(seed, str):
        raise RoomLobbyError("시드는 문자열이어야 합니다")
    seed = seed.strip()
    if seed and (not seed.isdigit() or int(seed) > 18446744073709551615):
        raise RoomLobbyError("시드는 0부터 18446744073709551615 사이의 정수여야 합니다")
    if mode == "seeded" and not seed:
        raise RoomLobbyError("시드 게임에는 시드 값이 필요합니다")
    result["seed"] = seed

    for key, low, high, label in (
            ("turn_seconds", 3, 60, "턴 제한 시간"),
            ("transition_seconds", 3, 60, "맵 이동 대기 시간"),
            ("max_players", 2, 8, "최대 플레이어 수")):
        value = result[key]
        if not isinstance(value, int) or isinstance(value, bool):
            raise RoomLobbyError("%s은(는) 정수여야 합니다" % label)
        if value < low or value > high:
            raise RoomLobbyError("%s은(는) %d에서 %d 사이여야 합니다" %
                                 (label, low, high))

    return result


@dataclass
class RoomMember:
    client_id: str
    display_name: str
    joined_at: float

    def public(self, host_id=None):
        return {
            "id": self.client_id,
            "name": self.display_name,
            "host": self.client_id == host_id,
        }


@dataclass
class PeerRoom:
    room_id: str
    title: str
    host_id: str
    settings: Dict[str, object]
    created_at: float
    state: RoomState = RoomState.WAITING
    started_at: Optional[float] = None
    players: "OrderedDict[str, RoomMember]" = field(default_factory=OrderedDict)
    spectators: "OrderedDict[str, RoomMember]" = field(default_factory=OrderedDict)

    def role_of(self, client_id):
        if client_id in self.players:
            return RoomRole.PLAYER
        if client_id in self.spectators:
            return RoomRole.SPECTATOR
        return None

    def member(self, client_id):
        return self.players.get(client_id) or self.spectators.get(client_id)

    def public(self):
        host = self.players.get(self.host_id)
        return {
            "id": self.room_id,
            "title": self.title,
            "state": self.state.value,
            "host_id": self.host_id,
            "host_name": host.display_name if host else "",
            "settings": dict(self.settings),
            "players": [member.public(self.host_id)
                        for member in self.players.values()],
            "player_count": len(self.players),
            "spectator_count": len(self.spectators),
            "joinable": (self.state == RoomState.WAITING and
                         len(self.players) < self.settings["max_players"]),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "topology": "p2p_hosted",
        }

    def private_for(self, client_id):
        result = self.public()
        role = self.role_of(client_id)
        result.update({
            "self_id": client_id,
            "self_role": role.value if role else None,
            "spectators": [member.public(self.host_id)
                           for member in self.spectators.values()],
        })
        return result


class RoomDirectory:
    """In-memory room directory owned by one dedicated WebTiles process."""

    def __init__(self, clock=None, id_factory=None):
        self.clock = clock or time.time
        self.id_factory = id_factory or (lambda: secrets.token_hex(4))
        self.rooms = OrderedDict()
        self.client_rooms = {}  # type: Dict[str, str]

    def list_rooms(self):
        return [room.public() for room in self.rooms.values()]

    def room_for_client(self, client_id):
        room_id = self.client_rooms.get(client_id)
        return self.rooms.get(room_id) if room_id else None

    def get(self, room_id):
        try:
            return self.rooms[room_id]
        except KeyError:
            raise RoomLobbyError("존재하지 않거나 종료된 방입니다")

    def create(self, client_id, display_name, title, settings=None):
        self._require_free_client(client_id)
        display_name = normalize_display_name(display_name)
        title = normalize_room_title(title)
        settings = normalize_world_settings(settings)

        room_id = self.id_factory()
        while room_id in self.rooms:
            room_id = self.id_factory()
        now = float(self.clock())
        room = PeerRoom(room_id, title, client_id, settings, now)
        room.players[client_id] = RoomMember(client_id, display_name, now)
        self.rooms[room_id] = room
        self.client_rooms[client_id] = room_id
        return room

    def join(self, room_id, client_id, display_name, spectator=False):
        self._require_free_client(client_id)
        room = self.get(room_id)
        display_name = normalize_display_name(display_name)
        now = float(self.clock())

        if spectator:
            room.spectators[client_id] = RoomMember(
                client_id, display_name, now)
        else:
            if room.state != RoomState.WAITING:
                raise RoomLobbyError("이미 시작된 방에는 플레이어로 난입할 수 없습니다")
            if len(room.players) >= room.settings["max_players"]:
                raise RoomLobbyError("방의 플레이어 자리가 가득 찼습니다")
            room.players[client_id] = RoomMember(client_id, display_name, now)

        self.client_rooms[client_id] = room_id
        return room

    def rename(self, client_id, display_name):
        display_name = normalize_display_name(display_name)
        room = self.room_for_client(client_id)
        if room:
            room.member(client_id).display_name = display_name
        return room

    def start(self, client_id):
        room = self._owned_room(client_id)
        if room.state != RoomState.WAITING:
            raise RoomLobbyError("이미 시작된 방입니다")
        room.state = RoomState.RUNNING
        room.started_at = float(self.clock())
        return room

    def leave(self, client_id):
        room = self.room_for_client(client_id)
        if room is None:
            return None, False

        was_host = room.host_id == client_id
        room.players.pop(client_id, None)
        room.spectators.pop(client_id, None)
        self.client_rooms.pop(client_id, None)

        # A running P2P world is host-authoritative, so it cannot migrate after
        # the host leaves. Waiting rooms can safely elect the oldest player.
        closed = False
        if was_host and room.state == RoomState.RUNNING:
            self._close(room)
            closed = True
        elif was_host and room.players:
            room.host_id = next(iter(room.players))
        elif not room.players:
            self._close(room)
            closed = True
        return room, closed

    def close(self, client_id):
        room = self._owned_room(client_id)
        self._close(room)
        return room

    def validate_signal(self, sender_id, target_id, signal):
        room = self.room_for_client(sender_id)
        if room is None or room.member(target_id) is None:
            raise RoomLobbyError("같은 방에 있는 사용자에게만 P2P 신호를 보낼 수 있습니다")
        if sender_id == target_id:
            raise RoomLobbyError("자기 자신에게 P2P 신호를 보낼 수 없습니다")
        if not isinstance(signal, Mapping):
            raise RoomLobbyError("P2P 신호는 객체 형식이어야 합니다")
        signal_type = signal.get("type")
        if signal_type not in ("offer", "answer", "ice"):
            raise RoomLobbyError("허용되지 않은 P2P 신호입니다")
        if len(json.dumps(signal, separators=(",", ":"))) > MAX_SIGNAL_BYTES:
            raise RoomLobbyError("P2P 신호가 너무 큽니다")
        return room

    def _owned_room(self, client_id):
        room = self.room_for_client(client_id)
        if room is None or room.host_id != client_id:
            raise RoomLobbyError("방장만 실행할 수 있는 작업입니다")
        return room

    def _require_free_client(self, client_id):
        if not isinstance(client_id, str) or not client_id:
            raise RoomLobbyError("잘못된 접속 ID입니다")
        if client_id in self.client_rooms:
            raise RoomLobbyError("먼저 현재 방에서 나가야 합니다")

    def _close(self, room):
        self.rooms.pop(room.room_id, None)
        for client_id in list(room.players) + list(room.spectators):
            self.client_rooms.pop(client_id, None)

