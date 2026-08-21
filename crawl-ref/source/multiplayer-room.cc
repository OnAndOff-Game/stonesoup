#include "AppHdr.h"

#include "multiplayer-room.h"

#include <algorithm>
#include <map>
#include <set>
#include <stdexcept>
#include <utility>

#include "env.h"
#include "player-context.h"
#include "player.h"

namespace multiplayer
{
namespace
{

room* current_room = nullptr;

struct player_view_state
{
    player_view_state()
        : map_seen(env.map_seen), map_knowledge(env.map_knowledge),
          map_forgotten(env.map_forgotten
                        ? new MapKnowledge(*env.map_forgotten) : nullptr),
          visible(env.visible), travel_trail(env.travel_trail)
    {
    }

    map_bitmask map_seen;
    MapKnowledge map_knowledge;
    std::unique_ptr<MapKnowledge> map_forgotten;
    std::set<coord_def> visible;
    std::vector<coord_def> travel_trail;
};

struct player_slot
{
    player_id id = NO_PLAYER;
    std::string connection_id;
    std::unique_ptr<player> owned_actor;
    player* actor = nullptr;
    std::unique_ptr<player_view_state> view;
};

const std::pair<const char*, command_type> protocol_commands[] =
{
    { "move_left",       CMD_MOVE_LEFT },
    { "move_down",       CMD_MOVE_DOWN },
    { "move_up",         CMD_MOVE_UP },
    { "move_right",      CMD_MOVE_RIGHT },
    { "move_up_left",    CMD_MOVE_UP_LEFT },
    { "move_down_left",  CMD_MOVE_DOWN_LEFT },
    { "move_up_right",   CMD_MOVE_UP_RIGHT },
    { "move_down_right", CMD_MOVE_DOWN_RIGHT },
    { "wait",            CMD_WAIT },
    { "pickup",          CMD_PICKUP },
    { "go_upstairs",     CMD_GO_UPSTAIRS },
    { "go_downstairs",   CMD_GO_DOWNSTAIRS },
};

} // namespace

struct room::impl
{
    std::vector<player_slot> players;
    player_id next_id = 1;
    mid_t shared_last_mid = 0;
    uint64_t active_turn = 0;
    bool is_collecting = false;
    std::vector<player_id> priority;
    std::map<player_id, turn_command> submissions;
};

struct scoped_player_turn::impl
{
    room* shared_room = nullptr;
    room* previous_room = nullptr;
    player_slot* slot = nullptr;
    std::unique_ptr<scoped_player_context> player_context;

    explicit impl(room& target_room, player_id id)
        : shared_room(&target_room), previous_room(current_room)
    {
        auto& slots = target_room._impl->players;
        const auto found = std::find_if(slots.begin(), slots.end(),
            [id](const player_slot& candidate) { return candidate.id == id; });
        if (found == slots.end())
            throw std::invalid_argument("unknown multiplayer player");

        slot = &*found;
        current_room = &target_room;
        slot->actor->last_mid = target_room._impl->shared_last_mid;
        player_context.reset(new scoped_player_context(*slot->actor));

        using std::swap;
        swap(env.map_seen, slot->view->map_seen);
        swap(env.map_knowledge, slot->view->map_knowledge);
        swap(env.map_forgotten, slot->view->map_forgotten);
        swap(env.visible, slot->view->visible);
        swap(env.travel_trail, slot->view->travel_trail);
    }

    ~impl()
    {
        shared_room->_impl->shared_last_mid = std::max(
            shared_room->_impl->shared_last_mid, slot->actor->last_mid);

        using std::swap;
        swap(env.travel_trail, slot->view->travel_trail);
        swap(env.visible, slot->view->visible);
        swap(env.map_forgotten, slot->view->map_forgotten);
        swap(env.map_knowledge, slot->view->map_knowledge);
        swap(env.map_seen, slot->view->map_seen);

        player_context.reset();
        current_room = previous_room;
    }
};

room::room() : _impl(new impl)
{
}

room::~room() = default;

player_id room::add_player(player& actor, const std::string& connection_id)
{
    if (_impl->players.size() >= MAX_ROOM_PLAYERS)
        return NO_PLAYER;
    for (const player_slot& slot : _impl->players)
    {
        if (slot.actor == &actor
            || (!connection_id.empty() && slot.connection_id == connection_id))
        {
            return NO_PLAYER;
        }
    }

    const player_id id = _impl->next_id++;
    player_slot slot;
    slot.id = id;
    slot.connection_id = connection_id;
    slot.actor = &actor;
    slot.actor->mid = mid_for_player(id);
    _impl->shared_last_mid = std::max(_impl->shared_last_mid,
                                      slot.actor->last_mid);
    slot.view.reset(new player_view_state);
    _impl->players.push_back(std::move(slot));
    return id;
}

player_id room::emplace_player(const std::string& connection_id)
{
    std::unique_ptr<player> actor(new player);
    player* actor_ptr = actor.get();
    const player_id id = add_player(*actor_ptr, connection_id);
    if (id == NO_PLAYER)
        return NO_PLAYER;

    auto found = std::find_if(_impl->players.begin(), _impl->players.end(),
        [id](const player_slot& slot) { return slot.id == id; });
    found->owned_actor = std::move(actor);
    return id;
}

bool room::remove_player(player_id id)
{
    if (_impl->is_collecting)
        return false;
    auto found = std::find_if(_impl->players.begin(), _impl->players.end(),
        [id](const player_slot& slot) { return slot.id == id; });
    if (found == _impl->players.end())
        return false;
    if (!found->owned_actor)
        found->actor->mid = MID_PLAYER;
    _impl->players.erase(found);
    return true;
}

player* room::find_player(player_id id)
{
    for (player_slot& slot : _impl->players)
        if (slot.id == id)
            return slot.actor;
    return nullptr;
}

const player* room::find_player(player_id id) const
{
    for (const player_slot& slot : _impl->players)
        if (slot.id == id)
            return slot.actor;
    return nullptr;
}

player* room::find_player_by_mid(mid_t mid)
{
    for (player_slot& slot : _impl->players)
        if (slot.actor->mid == mid)
            return slot.actor;
    return nullptr;
}

const player* room::find_player_by_mid(mid_t mid) const
{
    for (const player_slot& slot : _impl->players)
        if (slot.actor->mid == mid)
            return slot.actor;
    return nullptr;
}

player* room::find_player_at(const coord_def& pos)
{
    for (player_slot& slot : _impl->players)
    {
        if (slot.actor->on_current_level && slot.actor->alive()
            && slot.actor->pos() == pos)
        {
            return slot.actor;
        }
    }
    return nullptr;
}

const player* room::find_player_at(const coord_def& pos) const
{
    for (const player_slot& slot : _impl->players)
    {
        if (slot.actor->on_current_level && slot.actor->alive()
            && slot.actor->pos() == pos)
        {
            return slot.actor;
        }
    }
    return nullptr;
}

std::vector<player_id> room::player_ids() const
{
    std::vector<player_id> result;
    result.reserve(_impl->players.size());
    for (const player_slot& slot : _impl->players)
        result.push_back(slot.id);
    return result;
}

bool room::begin_turn(uint64_t turn_number,
                      const std::vector<player_id>& priority_order)
{
    if (_impl->is_collecting || turn_number == 0
        || turn_number <= _impl->active_turn || priority_order.empty())
    {
        return false;
    }

    std::set<player_id> unique;
    for (player_id id : priority_order)
    {
        if (!find_player(id) || !unique.insert(id).second)
            return false;
    }

    _impl->active_turn = turn_number;
    _impl->priority = priority_order;
    _impl->submissions.clear();
    _impl->is_collecting = true;
    return true;
}

submit_result room::submit(const turn_command& command)
{
    if (!_impl->is_collecting)
        return submit_result::not_collecting;
    if (command.turn_number != _impl->active_turn)
        return submit_result::wrong_turn;
    if (!find_player(command.player))
        return submit_result::unknown_player;
    if (std::find(_impl->priority.begin(), _impl->priority.end(), command.player)
        == _impl->priority.end())
    {
        return submit_result::player_not_eligible;
    }
    if (command.command == CMD_NO_CMD
        || protocol_command_name(command.command) == nullptr)
    {
        return submit_result::invalid_command;
    }

    const auto previous = _impl->submissions.find(command.player);
    if (previous != _impl->submissions.end())
    {
        if (!command.request_id.empty()
            && previous->second.request_id == command.request_id)
        {
            return submit_result::duplicate;
        }
        return submit_result::already_submitted;
    }

    _impl->submissions[command.player] = command;
    return submit_result::accepted;
}

bool room::all_submitted() const
{
    return _impl->is_collecting
           && _impl->submissions.size() == _impl->priority.size();
}

std::vector<turn_command> room::resolve_turn()
{
    std::vector<turn_command> commands;
    if (!_impl->is_collecting)
        return commands;

    commands.reserve(_impl->priority.size());
    for (player_id id : _impl->priority)
    {
        const auto submitted = _impl->submissions.find(id);
        if (submitted != _impl->submissions.end())
            commands.push_back(submitted->second);
        else
        {
            turn_command wait;
            wait.turn_number = _impl->active_turn;
            wait.player = id;
            wait.command = CMD_WAIT;
            wait.automatic = true;
            commands.push_back(wait);
        }
    }

    _impl->is_collecting = false;
    _impl->priority.clear();
    _impl->submissions.clear();
    return commands;
}

bool room::collecting() const
{
    return _impl->is_collecting;
}

uint64_t room::turn_number() const
{
    return _impl->active_turn;
}

scoped_player_turn::scoped_player_turn(room& shared_room, player_id id)
    : _impl(new impl(shared_room, id))
{
}

scoped_player_turn::~scoped_player_turn() = default;

room* active_room()
{
    return current_room;
}

player* player_by_mid(mid_t mid)
{
    return current_room ? current_room->find_player_by_mid(mid) : nullptr;
}

player* player_at(const coord_def& pos)
{
    return current_room ? current_room->find_player_at(pos) : nullptr;
}

mid_t mid_for_player(player_id id)
{
    if (id == NO_PLAYER || id > MAX_ROOM_PLAYERS)
        return MID_NOBODY;
    return MID_PLAYER - (id - 1);
}

bool protocol_command(const std::string& name, command_type& command)
{
    for (const auto& item : protocol_commands)
    {
        if (name == item.first)
        {
            command = item.second;
            return true;
        }
    }
    return false;
}

const char* protocol_command_name(command_type command)
{
    for (const auto& item : protocol_commands)
        if (command == item.second)
            return item.first;
    return nullptr;
}

} // namespace multiplayer
