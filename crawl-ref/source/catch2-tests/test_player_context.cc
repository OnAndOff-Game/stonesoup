#include "AppHdr.h"

#include "catch2-tests/catch_amalgamated.hpp"
#include "player-context.h"

TEST_CASE("player context restores the previous active player")
{
    player* original = &you;

#ifdef USE_MULTIPLAYER
    player alternate;
    {
        multiplayer::scoped_player_context context(alternate);
        CHECK(&multiplayer::active_player() == &alternate);
        CHECK(&you == &alternate);
    }
#else
    {
        multiplayer::scoped_player_context context(you);
        CHECK(&multiplayer::active_player() == original);
    }
#endif

    CHECK(&you == original);
}
