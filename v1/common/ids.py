"""
Primary keys.

Every table uses a UUIDv7 primary key. Unlike UUIDv4 the first 48 bits are a
millisecond timestamp, so keys sort by creation time — which keeps B-tree
inserts appending at the right edge instead of scattering across the index, and
means `ORDER BY id` is a usable proxy for `ORDER BY created_at`.

Over a sequential integer it buys: ids that can be minted before insert, no
cross-tenant information leaked by a guessable id, and no collision when rows
arrive from more than one writer.
"""

import uuid

try:  # Python 3.14+
    from uuid import uuid7  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - exercised on 3.12/3.13
    from uuid_utils.compat import uuid7  # returns a stdlib uuid.UUID


def new_id() -> uuid.UUID:
    """A fresh time-ordered primary key."""
    return uuid7()


__all__ = ["new_id", "uuid7"]
