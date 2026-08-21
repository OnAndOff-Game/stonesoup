#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "command-type.h"
#include "coord.h"
#include "externs.h"

class player;

namespace multiplayer
{

using player_id = uint32_t;

static constexpr player_id NO_PLAYER = 0;
static constexpr player_id MAX_ROOM_PLAYERS = 8;

enum class submit_result
{
    accepted,
    duplicate,
    not_collecting,
    wrong_turn,
    unknown_player,
    player_not_eligible,
    already_submitted,
    invalid_command,
};

struct turn_command
{
    uint64_t turn_number = 0;
    player_id player = NO_PLAYER;
    command_type command = CMD_NO_CMD;
    std::string request_id;
    bool automatic = false;
};

/** Shared-world player registry and deterministic input queue. */
class room
{
public:
    room();
    ~room();

    room(const room&) = delete;
    room& operator=(const room&) = delete;

    player_id add_player(player& actor,
                         const std::string& connection_id = std::string());
    player_id emplace_player(
                         const std::string& connection_id = std::string());
    bool remove_player(player_id id);

    player* find_player(player_id id);
    const player* find_player(player_id id) const;
    player* find_player_by_mid(mid_t mid);
    const player* find_player_by_mid(mid_t mid) const;
    player* find_player_at(const coord_def& pos);
    const player* find_player_at(const coord_def& pos) const;
    std::vector<player_id> player_ids() const;

    bool begin_turn(uint64_t turn_number,
                    const std::vector<player_id>& priority_order);
    submit_result submit(const turn_command& command);
    bool all_submitted() const;
    std::vector<turn_command> resolve_turn();
    bool collecting() const;
    uint64_t turn_number() const;

private:
    struct impl;
    std::unique_ptr<impl> _impl;

    friend class scoped_player_turn;
};

/**
 * Activate one room player and that player's private exploration state.
 * Existing code may use `you` and env.map_knowledge inside this scope.
 */
class scoped_player_turn
{
public:
    scoped_player_turn(room& shared_room, player_id id);
    ~scoped_player_turn();

    scoped_player_turn(const scoped_player_turn&) = delete;
    scoped_player_turn& operator=(const scoped_player_turn&) = delete;

private:
    struct impl;
    std::unique_ptr<impl> _impl;
};

room* active_room();
player* player_by_mid(mid_t mid);
player* player_at(const coord_def& pos);

mid_t mid_for_player(player_id id);
bool protocol_command(const std::string& name, command_type& command);
const char* protocol_command_name(command_type command);

} // namespace multiplayer
