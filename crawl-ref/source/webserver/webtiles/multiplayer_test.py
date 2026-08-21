import unittest
import json

from webtiles.multiplayer import AdvanceReason
from webtiles.multiplayer import CoordinatorError
from webtiles.multiplayer import LifeState
from webtiles.multiplayer import MapTransitionCoordinator
from webtiles.multiplayer import RoomEngineBridge
from webtiles.multiplayer import TransitionState
from webtiles.multiplayer import TurnCoordinator
from webtiles.multiplayer import resolve_player_movements
from webtiles.multiplayer import validate_client_command


class TurnCoordinatorTest(unittest.TestCase):

    def make_room(self, turn_seconds=10):
        room = TurnCoordinator(turn_seconds=turn_seconds)
        room.add_player("a")
        room.add_player("b")
        room.start(now=100)
        return room

    def test_all_ready_resolves_without_waiting_for_deadline(self):
        room = self.make_room()
        room.submit("a", "move", {"x": 1}, request_id="a-1")
        room.submit("b", "wait", request_id="b-1")

        self.assertTrue(room.should_resolve(now=101))
        resolution = room.resolve(now=101)

        self.assertEqual(AdvanceReason.ALL_READY, resolution.reason)
        self.assertEqual(["a", "b"], [a.player_id for a in resolution.actions])

    def test_timeout_supplies_automatic_wait(self):
        room = self.make_room()
        room.submit("a", "move")

        resolution = room.resolve(now=110)

        self.assertEqual(AdvanceReason.TIMEOUT, resolution.reason)
        waiting = resolution.actions[1]
        self.assertEqual("b", waiting.player_id)
        self.assertEqual("wait", waiting.action)
        self.assertTrue(waiting.automatic)

    def test_disconnected_and_afk_players_do_not_hold_turn(self):
        room = self.make_room()
        room.set_connected("b", False)
        room.submit("a", "wait")

        self.assertTrue(room.all_ready())
        resolution = room.resolve(now=101)
        self.assertTrue(resolution.actions[1].automatic)

    def test_duplicate_request_is_idempotent_but_new_action_is_rejected(self):
        room = self.make_room()
        first = room.submit("a", "move", request_id="same-id")

        self.assertIs(first, room.submit("a", "move", request_id="same-id"))
        with self.assertRaises(CoordinatorError):
            room.submit("a", "wait", request_id="different-id")

    def test_resolution_priority_rotates_each_turn(self):
        room = self.make_room()
        room.submit("a", "wait")
        room.submit("b", "wait")
        room.resolve(now=101)
        room.begin_next_turn(now=102)

        self.assertEqual(("b", "a"), room.priority_order())

    def test_two_missed_deadlines_mark_player_afk(self):
        room = self.make_room()
        for now in (110, 120):
            room.submit("a", "wait", request_id="a-%s" % now)
            room.resolve(now=now)
            room.begin_next_turn(now=now)

        self.assertTrue(room.players["b"].afk)
        self.assertEqual(("a",), room.required_player_ids())

        room.set_afk("b", False)
        self.assertFalse(room.players["b"].afk)
        self.assertEqual(0, room.players["b"].missed_turns)

    def test_downed_player_expires_to_spectator_and_revives_next_floor(self):
        room = self.make_room()
        room.down_player("b")

        for now in (101, 102, 103, 104):
            room.submit("a", "wait", request_id="a-%s" % now)
            room.resolve(now=now)
            room.begin_next_turn(now=now + 0.5)

        self.assertEqual(LifeState.SPECTATOR, room.players["b"].life_state)
        self.assertEqual(("b",), room.revive_spectators_for_new_floor())
        self.assertEqual(LifeState.ACTIVE, room.players["b"].life_state)


class MovementResolutionTest(unittest.TestCase):

    def test_rotating_priority_wins_same_destination(self):
        result = resolve_player_movements(
            positions={"a": (0, 0), "b": (2, 0)},
            targets={"a": (1, 0), "b": (1, 0)},
            priority=("b", "a"),
        )

        self.assertEqual({"b": (1, 0)}, result.accepted)
        self.assertEqual("contested", result.rejected["a"])

    def test_players_can_follow_into_cells_vacated_in_same_batch(self):
        result = resolve_player_movements(
            positions={"a": (0, 0), "b": (1, 0)},
            targets={"a": (1, 0), "b": (2, 0)},
            priority=("a", "b"),
        )

        self.assertEqual({"a": (1, 0), "b": (2, 0)}, result.accepted)

    def test_swap_is_atomic(self):
        result = resolve_player_movements(
            positions={"a": (0, 0), "b": (1, 0)},
            targets={"a": (1, 0), "b": (0, 0)},
            priority=("a", "b"),
        )

        self.assertEqual({"a": (1, 0), "b": (0, 0)}, result.accepted)

    def test_stationary_ally_blocks_chain(self):
        result = resolve_player_movements(
            positions={"a": (0, 0), "b": (1, 0)},
            targets={"a": (1, 0)},
            priority=("a", "b"),
        )

        self.assertEqual({}, result.accepted)
        self.assertEqual("occupied", result.rejected["a"])


class RoomEngineBridgeTest(unittest.TestCase):

    def make_bridge(self, turn_seconds=10):
        room = TurnCoordinator(turn_seconds=turn_seconds)
        room.add_player("socket-a")
        room.add_player("socket-b")
        room.start(now=100)
        messages = []
        bridge = RoomEngineBridge(
            room,
            {"socket-a": 1, "socket-b": 2},
            messages.append,
        )
        return room, bridge, messages

    def test_mobile_direction_is_normalized_before_queueing(self):
        command = validate_client_command({"kind": "text", "text": "y"})

        self.assertEqual("move", command.action)
        self.assertEqual("move_up_left", command.engine_command)
        self.assertEqual({"dx": -1, "dy": -1}, command.payload)

    def test_non_atomic_menu_and_macro_commands_are_rejected(self):
        for text in ("i", "o", "z", "ab"):
            with self.subTest(text=text):
                with self.assertRaises(CoordinatorError):
                    validate_client_command({"kind": "text", "text": text})

    def test_resolved_turn_is_sent_as_versioned_engine_batch(self):
        room, bridge, messages = self.make_bridge()
        bridge.submit_client_command(
            "socket-a", 1, {"kind": "text", "text": "h"}, "a-1")

        resolution, batch = bridge.resolve_and_send(now=110)

        self.assertEqual(AdvanceReason.TIMEOUT, resolution.reason)
        self.assertEqual("multiplayer_command_batch", batch["msg"])
        self.assertEqual(1, batch["schema"])
        self.assertEqual([1, 2], [item["player"] for item in batch["commands"]])
        self.assertEqual("move_left", batch["commands"][0]["command"])
        self.assertEqual("wait", batch["commands"][1]["command"])
        self.assertTrue(batch["commands"][1]["automatic"])
        self.assertEqual(batch, json.loads(messages[0]))
        self.assertNotIn("socket-a", messages[0])

    def test_stale_turn_is_rejected_before_submission(self):
        room, bridge, _messages = self.make_bridge()

        with self.assertRaises(CoordinatorError):
            bridge.submit_client_command(
                "socket-a", 2, {"kind": "text", "text": "."}, "a-2")

        self.assertEqual({}, room._submissions)


class MapTransitionCoordinatorTest(unittest.TestCase):

    def make_players(self):
        room = TurnCoordinator(turn_seconds=10)
        room.add_player("a")
        room.add_player("b")
        room.add_player("c")
        return room.players

    def test_everyone_ready_and_near_commits_immediately(self):
        players = self.make_players()
        travel = MapTransitionCoordinator(gather_distance=4, timeout_seconds=10)
        travel.start("a", "D:2", players, now=100)
        travel.mark_ready("b", players)
        travel.mark_ready("c", players)

        decision = travel.evaluate(
            players, {"a": 0, "b": 2, "c": 4}, now=101)

        self.assertEqual(TransitionState.COMMIT, decision.state)
        self.assertEqual("party_ready", decision.reason)

    def test_nearby_players_auto_follow_at_timeout(self):
        players = self.make_players()
        travel = MapTransitionCoordinator(gather_distance=4, timeout_seconds=10)
        travel.start("a", "D:2", players, now=100)

        decision = travel.evaluate(
            players, {"a": 0, "b": 2, "c": 4}, now=110)

        self.assertEqual(TransitionState.COMMIT, decision.state)
        self.assertEqual("timeout_auto_follow", decision.reason)

    def test_far_active_player_cancels_at_timeout(self):
        players = self.make_players()
        travel = MapTransitionCoordinator(gather_distance=4, timeout_seconds=10)
        travel.start("a", "D:2", players, now=100)

        decision = travel.evaluate(
            players, {"a": 0, "b": 2, "c": 8}, now=110)

        self.assertEqual(TransitionState.CANCEL, decision.state)
        self.assertEqual("active_player_too_far", decision.reason)

    def test_afk_player_cannot_block_transition(self):
        players = self.make_players()
        players["c"].afk = True
        travel = MapTransitionCoordinator(gather_distance=4, timeout_seconds=10)
        travel.start("a", "D:2", players, now=100)
        travel.mark_ready("b", players)

        decision = travel.evaluate(
            players, {"a": 0, "b": 2, "c": 99}, now=101)

        self.assertEqual(TransitionState.COMMIT, decision.state)
        self.assertIn("c", decision.followers)


if __name__ == "__main__":
    unittest.main()
