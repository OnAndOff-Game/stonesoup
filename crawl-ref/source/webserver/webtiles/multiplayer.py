"""Server-authoritative coordination primitives for cooperative Crawl.

This module deliberately does not depend on Tornado or the Crawl process
handler.  It contains the deterministic room rules that the websocket layer
and, later, the shared-world C++ process will both use.
"""

from dataclasses import dataclass
from enum import Enum
import json
from typing import Dict
from typing import Callable
from typing import List
from typing import Mapping
from typing import Optional
from typing import Tuple


Coordinate = Tuple[int, int]


class CoordinatorError(ValueError):
    """Raised when a client requests an invalid room state transition."""


class RoomPhase(str, Enum):
    LOBBY = "lobby"
    COLLECTING = "collecting"
    RESOLVED = "resolved"


class AdvanceReason(str, Enum):
    ALL_READY = "all_ready"
    TIMEOUT = "timeout"


class LifeState(str, Enum):
    ACTIVE = "active"
    DOWNED = "downed"
    SPECTATOR = "spectator"


class TransitionState(str, Enum):
    PENDING = "pending"
    COMMIT = "commit"
    CANCEL = "cancel"


@dataclass
class PlayerSlot:
    player_id: str
    join_index: int
    connected: bool = True
    afk: bool = False
    life_state: LifeState = LifeState.ACTIVE
    downed_until_turn: Optional[int] = None
    missed_turns: int = 0


@dataclass(frozen=True)
class PlayerAction:
    player_id: str
    action: str
    payload: Tuple[Tuple[str, object], ...] = ()
    request_id: Optional[str] = None
    automatic: bool = False
    engine_command: Optional[str] = None

    @classmethod
    def create(cls, player_id, action, payload=None, request_id=None,
               engine_command=None):
        # Sorting only by the string key keeps construction deterministic even
        # when payload values are different, non-orderable Python types.
        items = tuple(sorted((payload or {}).items(), key=lambda item: item[0]))
        return cls(player_id, action, items, request_id, False, engine_command)

    @classmethod
    def wait(cls, player_id):
        return cls(player_id, "wait", (), None, True, "wait")


@dataclass(frozen=True)
class TurnResolution:
    turn_number: int
    reason: AdvanceReason
    actions: Tuple[PlayerAction, ...]


class TurnCoordinator:
    """Collect exactly one action from each available player per room turn.

    Missing, disconnected, AFK, and downed players never hold the room open.
    Active players who miss the deadline receive an automatic wait action.
    Player resolution priority rotates every turn to avoid permanent host
    advantage when two actions conflict.
    """

    def __init__(self, turn_seconds, downed_rounds=3, auto_afk_after=2):
        if turn_seconds < 1 or turn_seconds > 300:
            raise CoordinatorError("턴 제한 시간은 1초에서 300초 사이여야 합니다")
        if downed_rounds < 1:
            raise CoordinatorError("쓰러짐 유지 턴 수는 양수여야 합니다")
        if auto_afk_after < 1:
            raise CoordinatorError("자동 자리 비움 기준은 양수여야 합니다")

        self.turn_seconds = float(turn_seconds)
        self.downed_rounds = int(downed_rounds)
        self.auto_afk_after = int(auto_afk_after)
        self.phase = RoomPhase.LOBBY
        self.turn_number = 0
        self.deadline = None  # type: Optional[float]
        self.players = {}  # type: Dict[str, PlayerSlot]
        self._submissions = {}  # type: Dict[str, PlayerAction]
        self._last_resolution = None  # type: Optional[TurnResolution]
        self._next_join_index = 0

    def add_player(self, player_id, connected=True):
        if not player_id:
            raise CoordinatorError("플레이어 ID를 비워 둘 수 없습니다")
        if player_id in self.players:
            raise CoordinatorError("이미 참가한 플레이어입니다")
        self.players[player_id] = PlayerSlot(
            player_id=player_id,
            join_index=self._next_join_index,
            connected=connected,
        )
        self._next_join_index += 1

    def set_connected(self, player_id, connected):
        self._player(player_id).connected = bool(connected)

    def set_afk(self, player_id, afk):
        player = self._player(player_id)
        player.afk = bool(afk)
        if not player.afk:
            player.missed_turns = 0

    def start(self, now):
        if self.phase != RoomPhase.LOBBY:
            raise CoordinatorError("방이 이미 시작되었습니다")
        if not self.players:
            raise CoordinatorError("빈 방은 시작할 수 없습니다")
        self.turn_number = 1
        self.phase = RoomPhase.COLLECTING
        self.deadline = float(now) + self.turn_seconds

    def submit(self, player_id, action, payload=None, request_id=None,
               engine_command=None):
        if self.phase != RoomPhase.COLLECTING:
            raise CoordinatorError("현재 행동을 받는 단계가 아닙니다")
        player = self._player(player_id)
        if not self._is_required(player):
            raise CoordinatorError("이 플레이어는 이번 턴에 행동할 수 없습니다")

        submission = PlayerAction.create(
            player_id, action, payload=payload, request_id=request_id,
            engine_command=engine_command)
        previous = self._submissions.get(player_id)
        if previous is not None:
            if request_id is not None and previous.request_id == request_id:
                return previous
            raise CoordinatorError("이미 이번 턴의 행동을 제출했습니다")

        self._submissions[player_id] = submission
        return submission

    def required_player_ids(self):
        return tuple(
            player.player_id
            for player in self._players_in_join_order()
            if self._is_required(player)
        )

    def all_ready(self):
        required = self.required_player_ids()
        return bool(required) and all(
            player_id in self._submissions for player_id in required)

    def should_resolve(self, now):
        if self.phase != RoomPhase.COLLECTING:
            return False
        return self.all_ready() or float(now) >= self.deadline

    def resolve(self, now):
        if not self.should_resolve(now):
            raise CoordinatorError("아직 이번 턴의 행동을 받는 중입니다")

        reason = (AdvanceReason.ALL_READY
                  if self.all_ready() else AdvanceReason.TIMEOUT)
        actions = []
        for player_id in self.priority_order():
            player = self.players[player_id]
            if player.life_state != LifeState.ACTIVE:
                continue
            actions.append(
                self._submissions.get(player_id, PlayerAction.wait(player_id)))

        resolution = TurnResolution(
            turn_number=self.turn_number,
            reason=reason,
            actions=tuple(actions),
        )
        self._update_missed_turns()
        self.phase = RoomPhase.RESOLVED
        self._last_resolution = resolution
        return resolution

    def begin_next_turn(self, now):
        if self.phase != RoomPhase.RESOLVED:
            raise CoordinatorError("현재 턴이 아직 처리되지 않았습니다")
        self.turn_number += 1
        self._expire_downed_players()
        self._submissions.clear()
        self.phase = RoomPhase.COLLECTING
        self.deadline = float(now) + self.turn_seconds

    def priority_order(self):
        active = [
            player.player_id
            for player in self._players_in_join_order()
            if player.life_state == LifeState.ACTIVE
        ]
        if not active:
            return tuple()
        offset = (max(self.turn_number, 1) - 1) % len(active)
        return tuple(active[offset:] + active[:offset])

    def down_player(self, player_id):
        player = self._player(player_id)
        if player.life_state != LifeState.ACTIVE:
            raise CoordinatorError("활동 중인 플레이어만 쓰러짐 상태가 될 수 있습니다")
        player.life_state = LifeState.DOWNED
        player.downed_until_turn = self.turn_number + self.downed_rounds
        self._submissions.pop(player_id, None)

    def revive_player(self, player_id):
        player = self._player(player_id)
        if player.life_state != LifeState.DOWNED:
            raise CoordinatorError("쓰러진 플레이어가 아닙니다")
        player.life_state = LifeState.ACTIVE
        player.downed_until_turn = None

    def revive_spectators_for_new_floor(self):
        revived = []
        for player in self._players_in_join_order():
            if player.life_state == LifeState.SPECTATOR:
                player.life_state = LifeState.ACTIVE
                player.downed_until_turn = None
                revived.append(player.player_id)
        return tuple(revived)

    def party_defeated(self):
        return not any(
            player.life_state == LifeState.ACTIVE
            for player in self.players.values()
        )

    def _expire_downed_players(self):
        for player in self.players.values():
            if (player.life_state == LifeState.DOWNED
                    and self.turn_number > player.downed_until_turn):
                player.life_state = LifeState.SPECTATOR
                player.downed_until_turn = None

    def _update_missed_turns(self):
        for player in self.players.values():
            if player.life_state != LifeState.ACTIVE or not player.connected:
                continue
            if player.player_id in self._submissions:
                player.missed_turns = 0
            elif not player.afk:
                player.missed_turns += 1
                if player.missed_turns >= self.auto_afk_after:
                    player.afk = True

    def _players_in_join_order(self):
        return sorted(self.players.values(), key=lambda player: player.join_index)

    @staticmethod
    def _is_required(player):
        return (player.life_state == LifeState.ACTIVE
                and player.connected and not player.afk)

    def _player(self, player_id):
        try:
            return self.players[player_id]
        except KeyError:
            raise CoordinatorError("알 수 없는 플레이어입니다")


@dataclass(frozen=True)
class ValidatedClientCommand:
    action: str
    engine_command: str
    payload: Mapping[str, object]


_MOVEMENT_KEYS = {
    "h": ("move_left", -1, 0),
    "j": ("move_down", 0, 1),
    "k": ("move_up", 0, -1),
    "l": ("move_right", 1, 0),
    "y": ("move_up_left", -1, -1),
    "b": ("move_down_left", -1, 1),
    "u": ("move_up_right", 1, -1),
    "n": ("move_down_right", 1, 1),
}


def validate_client_command(command):
    """Turn an untrusted mobile/desktop command into an atomic room action.

    Menus, macros, autoexplore, and arbitrary text are intentionally excluded:
    they can span multiple prompts or turns and therefore cannot be committed
    as one simultaneous room action.
    """

    if not isinstance(command, Mapping):
        raise CoordinatorError("명령은 객체 형식이어야 합니다")

    kind = command.get("kind")
    if kind == "text":
        key = command.get("text")
        if not isinstance(key, str) or len(key) != 1:
            raise CoordinatorError("텍스트 명령에는 정확히 한 키만 있어야 합니다")
    elif kind == "key":
        keycode = command.get("keycode")
        if not isinstance(keycode, int) or isinstance(keycode, bool):
            raise CoordinatorError("키 코드는 정수여야 합니다")
        if keycode < 0 or keycode > 127:
            raise CoordinatorError("멀티플레이 단일 행동으로 허용되지 않은 키 코드입니다")
        key = chr(keycode)
    else:
        raise CoordinatorError("알 수 없는 명령 종류입니다")

    if key in _MOVEMENT_KEYS:
        engine_command, dx, dy = _MOVEMENT_KEYS[key]
        return ValidatedClientCommand(
            action="move",
            engine_command=engine_command,
            payload={"dx": dx, "dy": dy},
        )
    if key in (".", "5"):
        return ValidatedClientCommand("wait", "wait", {})
    if key == "g":
        return ValidatedClientCommand("pickup", "pickup", {})
    if key == "<":
        return ValidatedClientCommand("transition", "go_upstairs", {})
    if key == ">":
        return ValidatedClientCommand("transition", "go_downstairs", {})

    raise CoordinatorError("멀티플레이 단일 행동으로 허용되지 않은 명령입니다")


def engine_command_batch(resolution, engine_player_ids):
    """Build the versioned JSON-compatible command batch consumed by C++."""

    commands = []
    for action in resolution.actions:
        try:
            engine_player_id = engine_player_ids[action.player_id]
        except KeyError:
            raise CoordinatorError("플레이어의 엔진 ID가 없습니다")
        if (not isinstance(engine_player_id, int)
                or isinstance(engine_player_id, bool)
                or engine_player_id < 1 or engine_player_id > 8):
            raise CoordinatorError("플레이어 엔진 ID는 1에서 8 사이여야 합니다")
        if action.engine_command is None:
            raise CoordinatorError("행동에 검증된 엔진 명령이 없습니다")

        commands.append({
            "player": engine_player_id,
            "command": action.engine_command,
            "request_id": action.request_id,
            "automatic": action.automatic,
            "payload": dict(action.payload),
        })

    return {
        "msg": "multiplayer_command_batch",
        "schema": 1,
        "turn": resolution.turn_number,
        "reason": resolution.reason.value,
        "commands": commands,
    }


class RoomEngineBridge:
    """Validate websocket actions and send resolved turns to one Crawl world.

    ``send_engine_message`` is the shared Crawl process control-socket sender.
    Keeping it injectable lets the room lifecycle own the process while this
    class remains deterministic and unit-testable.
    """

    def __init__(self, coordinator, engine_player_ids, send_engine_message):
        # type: (TurnCoordinator, Mapping[str, int], Callable[[str], None]) -> None
        self.coordinator = coordinator
        self.engine_player_ids = dict(engine_player_ids)
        self.send_engine_message = send_engine_message

        if set(self.engine_player_ids) != set(self.coordinator.players):
            raise CoordinatorError("방의 모든 플레이어에게 엔진 ID가 필요합니다")
        if len(set(self.engine_player_ids.values())) != len(
                self.engine_player_ids):
            raise CoordinatorError("플레이어 엔진 ID는 서로 달라야 합니다")

    def submit_client_command(self, player_id, turn, command, request_id):
        if turn != self.coordinator.turn_number:
            raise CoordinatorError("지난 턴 또는 아직 오지 않은 턴의 행동입니다")
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise CoordinatorError("요청 ID는 1자에서 128자 사이여야 합니다")

        validated = validate_client_command(command)
        return self.coordinator.submit(
            player_id,
            validated.action,
            payload=validated.payload,
            request_id=request_id,
            engine_command=validated.engine_command,
        )

    def resolve_and_send(self, now):
        resolution = self.coordinator.resolve(now)
        message = engine_command_batch(resolution, self.engine_player_ids)
        encoded = json.dumps(
            message, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        self.send_engine_message(encoded)
        return resolution, message


@dataclass(frozen=True)
class MovementResolution:
    accepted: Mapping[str, Coordinate]
    rejected: Mapping[str, str]


def resolve_player_movements(positions, targets, priority):
    """Resolve simultaneous one-cell player moves as one atomic batch.

    A rotating room priority decides contests for the same destination.  Moves
    into cells vacated in the same batch and closed cycles (including a two
    player swap) are allowed.  Moving into a stationary ally is rejected.
    Monster occupancy and attacks remain the simulation engine's concern.
    """

    positions = dict(positions)
    targets = dict(targets)
    rank = {player_id: index for index, player_id in enumerate(priority)}
    rejected = {}  # type: Dict[str, str]
    contenders = {}  # type: Dict[Coordinate, List[str]]

    for player_id, target in targets.items():
        if player_id not in positions:
            raise CoordinatorError("알 수 없는 플레이어가 이동을 제출했습니다")
        source = positions[player_id]
        if target == source:
            rejected[player_id] = "stationary"
            continue
        if max(abs(target[0] - source[0]), abs(target[1] - source[1])) != 1:
            raise CoordinatorError("플레이어는 정확히 한 칸만 이동해야 합니다")
        contenders.setdefault(target, []).append(player_id)

    candidates = {}  # type: Dict[str, Coordinate]
    fallback_rank = len(rank)
    for target, player_ids in contenders.items():
        ordered = sorted(
            player_ids,
            key=lambda player_id: (rank.get(player_id, fallback_rank), player_id),
        )
        candidates[ordered[0]] = target
        for player_id in ordered[1:]:
            rejected[player_id] = "contested"

    occupant = {position: player_id for player_id, position in positions.items()}
    movable = {}  # type: Dict[str, bool]
    visiting = set()

    def can_move(player_id):
        if player_id in movable:
            return movable[player_id]
        if player_id in visiting:
            # A dependency cycle is an atomic rotation and is therefore valid.
            movable[player_id] = True
            return True

        visiting.add(player_id)
        blocking_player = occupant.get(candidates[player_id])
        if blocking_player is None:
            result = True
        elif blocking_player not in candidates:
            result = False
        else:
            result = can_move(blocking_player)
        visiting.discard(player_id)
        movable[player_id] = result
        return result

    accepted = {}  # type: Dict[str, Coordinate]
    for player_id in candidates:
        if can_move(player_id):
            accepted[player_id] = candidates[player_id]
        else:
            rejected[player_id] = "occupied"

    return MovementResolution(accepted=accepted, rejected=rejected)


@dataclass(frozen=True)
class TransitionRequest:
    initiator_id: str
    destination: str
    deadline: float
    ready_players: Tuple[str, ...]


@dataclass(frozen=True)
class TransitionDecision:
    state: TransitionState
    reason: str
    followers: Tuple[str, ...] = ()


class MapTransitionCoordinator:
    """Coordinate party stair/portal travel without allowing AFK griefing."""

    def __init__(self, gather_distance=4, timeout_seconds=10):
        if gather_distance < 0:
            raise CoordinatorError("집결 거리는 음수일 수 없습니다")
        if timeout_seconds < 1 or timeout_seconds > 300:
            raise CoordinatorError("대기 제한 시간은 1초에서 300초 사이여야 합니다")
        self.gather_distance = int(gather_distance)
        self.timeout_seconds = float(timeout_seconds)
        self._initiator_id = None  # type: Optional[str]
        self._destination = None  # type: Optional[str]
        self._deadline = None  # type: Optional[float]
        self._ready_players = set()

    @property
    def active(self):
        return self._initiator_id is not None

    def start(self, initiator_id, destination, players, now):
        if self.active:
            raise CoordinatorError("이미 맵 이동을 준비 중입니다")
        player = _known_player(players, initiator_id)
        if player.life_state != LifeState.ACTIVE:
            raise CoordinatorError("활동 중인 플레이어만 맵 이동을 시작할 수 있습니다")
        self._initiator_id = initiator_id
        self._destination = destination
        self._deadline = float(now) + self.timeout_seconds
        self._ready_players = {initiator_id}
        return self.snapshot()

    def mark_ready(self, player_id, players):
        player = _known_player(players, player_id)
        if player.life_state != LifeState.ACTIVE:
            raise CoordinatorError("활동 중인 플레이어만 준비할 수 있습니다")
        if not self.active:
            raise CoordinatorError("진행 중인 맵 이동이 없습니다")
        self._ready_players.add(player_id)
        return self.snapshot()

    def evaluate(self, players, distance_to_exit, now):
        if not self.active:
            raise CoordinatorError("진행 중인 맵 이동이 없습니다")

        ordered = sorted(players.values(), key=lambda player: player.join_index)
        active_players = [
            player for player in ordered
            if player.life_state == LifeState.ACTIVE
        ]
        required = [
            player for player in active_players
            if player.connected and not player.afk
        ]

        all_ready = bool(required) and all(
            player.player_id in self._ready_players for player in required)
        all_near = all(
            distance_to_exit.get(player.player_id, float("inf"))
            <= self.gather_distance
            for player in required
        )
        followers = tuple(player.player_id for player in ordered)

        if all_ready and all_near:
            return TransitionDecision(
                TransitionState.COMMIT, "party_ready", followers)

        if float(now) < self._deadline:
            return TransitionDecision(TransitionState.PENDING, "gathering")

        far_active = [
            player.player_id for player in required
            if distance_to_exit.get(player.player_id, float("inf"))
            > self.gather_distance
        ]
        if far_active:
            return TransitionDecision(
                TransitionState.CANCEL, "active_player_too_far")
        return TransitionDecision(
            TransitionState.COMMIT, "timeout_auto_follow", followers)

    def snapshot(self):
        if not self.active:
            raise CoordinatorError("진행 중인 맵 이동이 없습니다")
        return TransitionRequest(
            initiator_id=self._initiator_id,
            destination=self._destination,
            deadline=self._deadline,
            ready_players=tuple(sorted(self._ready_players)),
        )

    def clear(self):
        self._initiator_id = None
        self._destination = None
        self._deadline = None
        self._ready_players.clear()


def _known_player(players, player_id):
    try:
        return players[player_id]
    except KeyError:
        raise CoordinatorError("알 수 없는 플레이어입니다")
