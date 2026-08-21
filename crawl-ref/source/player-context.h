/**
 * @file
 * @brief Selects the player actor used by legacy `you` call sites.
 *
 * The guard is intentionally small. It lets multiplayer command resolution
 * become explicit a subsystem at a time without a risky all-at-once rewrite
 * of every existing `you` reference.
 */

#pragma once

#include "player.h"

namespace multiplayer
{

inline player& active_player()
{
    return you;
}

class scoped_player_context
{
public:
    explicit scoped_player_context(player& next) : previous(&you)
    {
#ifdef USE_MULTIPLAYER
        active_you = &next;
#else
        // A non-multiplayer build keeps the original single-player invariant.
        ASSERT(&next == &you);
#endif
    }

    ~scoped_player_context()
    {
#ifdef USE_MULTIPLAYER
        active_you = previous;
#endif
    }

    scoped_player_context(const scoped_player_context&) = delete;
    scoped_player_context& operator=(const scoped_player_context&) = delete;

private:
    player* previous;
};

} // namespace multiplayer
