"""`democracy` is a mode this fork has and upstream does not — and the account
preference schema has to know that.

Upstream's `Preferences` model is `strict=True, extra="forbid"` over a closed
`Literal` of its own four modes. A sync that restores that four-value union
turns every preference write from a user whose last selection was Democracy into
a 422, and the fork's own mode becomes the one setting that cannot be saved.

The reason it needs pinning rather than trusting review: nothing else in the
suite constructs a `Preferences` with this mode, so narrowing the union back is
a green diff. The symptom only appears for the subset of users who chose
Democracy, and it appears as a failed background sync, not an error they see.

The negative case is here too: `extra="forbid"` plus a closed union is what
stops arbitrary run context from being persisted as an account preference, so a
sync must not "fix" this by loosening the field to a bare `str`.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.gateway.routers.user_preferences import Preferences

UPSTREAM_MODES = ("flash", "thinking", "pro", "ultra")


@pytest.mark.parametrize("mode", (*UPSTREAM_MODES, "democracy"))
def test_every_selectable_mode_round_trips_through_the_account_preference(mode: str):
    assert Preferences(mode=mode).mode == mode


def test_the_mode_union_stays_closed():
    """Widening it to a bare `str` would let run context become a stored preference."""
    with pytest.raises(ValidationError):
        Preferences(mode="not-a-mode")
