#include "AppHdr.h"

#include "catch2-tests/catch_amalgamated.hpp"
#include "mon-util.h"
#include "multiplayer-room.h"
#include "player.h"
#include "terrain.h"

TEST_CASE("multiplayer room assigns stable actor identities and positions")
{
#ifdef USE_MULTIPLAYER
    multiplayer::room shared_room;
    player first;
    player second;
    first.hp = second.hp = 1;
    first.on_current_level = second.on_current_level = true;
    first.set_position(coord_def(10, 10));
    second.set_position(coord_def(11, 10));

    const auto first_id = shared_room.add_player(first, "first");
    const auto second_id = shared_room.add_player(second, "second");

    REQUIRE(first_id != multiplayer::NO_PLAYER);
    REQUIRE(second_id != multiplayer::NO_PLAYER);
    CHECK(first.mid != second.mid);

    {
        multiplayer::scoped_player_turn context(shared_room, first_id);
        CHECK(&you == &first);
        CHECK(actor_by_mid(second.mid) == &second);
        CHECK(actor_at(second.pos()) == &second);
        you.last_mid = 41;
    }
    {
        multiplayer::scoped_player_turn context(shared_room, second_id);
        CHECK(you.last_mid == 41);
    }
#endif
}

TEST_CASE("multiplayer room queues one deterministic command per player")
{
#ifdef USE_MULTIPLAYER
    multiplayer::room shared_room;
    player first;
    player second;
    const auto first_id = shared_room.add_player(first, "first");
    const auto second_id = shared_room.add_player(second, "second");

    REQUIRE(shared_room.begin_turn(7, { second_id, first_id }));

    multiplayer::turn_command command;
    command.turn_number = 7;
    command.player = first_id;
    command.command = CMD_MOVE_LEFT;
    command.request_id = "request-1";

    CHECK(shared_room.submit(command) == multiplayer::submit_result::accepted);
    CHECK(shared_room.submit(command) == multiplayer::submit_result::duplicate);

    const auto commands = shared_room.resolve_turn();
    REQUIRE(commands.size() == 2);
    CHECK(commands[0].player == second_id);
    CHECK(commands[0].command == CMD_WAIT);
    CHECK(commands[0].automatic);
    CHECK(commands[1].player == first_id);
    CHECK(commands[1].command == CMD_MOVE_LEFT);
#endif
}

TEST_CASE("multiplayer protocol only accepts atomic room commands")
{
    command_type command = CMD_NO_CMD;
    CHECK(multiplayer::protocol_command("move_up_right", command));
    CHECK(command == CMD_MOVE_UP_RIGHT);
    CHECK_FALSE(multiplayer::protocol_command("save_game", command));
}
