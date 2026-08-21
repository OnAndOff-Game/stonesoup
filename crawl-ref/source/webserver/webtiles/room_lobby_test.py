import unittest

from webtiles.room_lobby import DEFAULT_WORLD_SETTINGS
from webtiles.room_lobby import RoomDirectory
from webtiles.room_lobby import RoomLobbyError
from webtiles.room_lobby import RoomState
from webtiles.room_lobby import normalize_world_settings


class RoomDirectoryTest(unittest.TestCase):
    def setUp(self):
        ids = iter(("room-a", "room-b"))
        self.now = 100.0
        self.directory = RoomDirectory(
            clock=lambda: self.now,
            id_factory=lambda: next(ids))

    def test_create_uses_unmodified_crawl_world_defaults(self):
        room = self.directory.create("host", "방장", "첫 모험")

        self.assertEqual(DEFAULT_WORLD_SETTINGS, room.settings)
        self.assertEqual(RoomState.WAITING, room.state)
        self.assertEqual("방장", room.public()["host_name"])
        self.assertTrue(room.public()["joinable"])

    def test_start_locks_player_join_but_keeps_spectating_open(self):
        room = self.directory.create("host", "방장", "잠긴 방")
        self.directory.join(room.room_id, "player", "동료")
        self.directory.start("host")

        with self.assertRaisesRegex(RoomLobbyError, "난입"):
            self.directory.join(room.room_id, "late", "지각생")

        watched = self.directory.join(
            room.room_id, "spectator", "관전자", spectator=True)
        self.assertEqual(1, len(watched.spectators))
        self.assertFalse(watched.public()["joinable"])

    def test_only_host_can_start(self):
        room = self.directory.create("host", "방장", "권한 검사")
        self.directory.join(room.room_id, "player", "동료")

        with self.assertRaisesRegex(RoomLobbyError, "방장"):
            self.directory.start("player")

    def test_waiting_room_migrates_host_but_running_room_closes(self):
        waiting = self.directory.create("host", "방장", "대기 중")
        self.directory.join(waiting.room_id, "player", "새 방장")
        room, closed = self.directory.leave("host")
        self.assertFalse(closed)
        self.assertEqual("player", room.host_id)

        self.directory.start("player")
        room, closed = self.directory.leave("player")
        self.assertTrue(closed)
        self.assertNotIn(room.room_id, self.directory.rooms)

    def test_signalling_is_limited_to_same_room_and_known_types(self):
        room = self.directory.create("host", "방장", "P2P")
        self.directory.join(room.room_id, "player", "동료")
        self.directory.validate_signal(
            "host", "player", {"type": "offer", "sdp": "test"})

        with self.assertRaisesRegex(RoomLobbyError, "같은 방"):
            self.directory.validate_signal(
                "host", "outsider", {"type": "offer", "sdp": "test"})
        with self.assertRaisesRegex(RoomLobbyError, "허용되지 않은"):
            self.directory.validate_signal(
                "host", "player", {"type": "arbitrary"})

    def test_player_limit_is_enforced(self):
        room = self.directory.create(
            "host", "방장", "둘만", {"max_players": 2})
        self.directory.join(room.room_id, "player", "동료")

        with self.assertRaisesRegex(RoomLobbyError, "가득"):
            self.directory.join(room.room_id, "third", "세 번째")


class WorldSettingsTest(unittest.TestCase):
    def test_seeded_mode_requires_seed(self):
        with self.assertRaisesRegex(RoomLobbyError, "시드 값"):
            normalize_world_settings({"game_mode": "seeded"})

    def test_custom_multiplayer_timing_keeps_other_defaults(self):
        settings = normalize_world_settings({
            "turn_seconds": 8,
            "transition_seconds": 12,
        })
        self.assertEqual("standard", settings["game_mode"])
        self.assertEqual(4, settings["max_players"])
        self.assertEqual(8, settings["turn_seconds"])
        self.assertEqual(12, settings["transition_seconds"])


if __name__ == "__main__":
    unittest.main()
