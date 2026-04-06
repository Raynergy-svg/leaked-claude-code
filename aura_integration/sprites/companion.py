"""Companion generation — deterministic PRNG, hashing, and stat rolling.

CRITICAL: The mulberry32 PRNG and FNV-1a hash must produce bit-identical
sequences to the original TypeScript implementation.  All arithmetic is
done in explicit 32-bit (signed or unsigned) to match JavaScript semantics.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, TypeVar

from src.aura.cli.sprites.types import (
    EYES,
    HATS,
    RARITIES,
    RARITY_WEIGHTS,
    SPECIES,
    STAT_NAMES,
    CompanionBones,
)

T = TypeVar("T")

# ─── 32-bit Arithmetic Helpers ─────────────────────────────────────────────

def _to_uint32(n: int) -> int:
    """Emulate JavaScript ``>>> 0`` — coerce to unsigned 32-bit integer."""
    return n & 0xFFFFFFFF


def _to_int32(n: int) -> int:
    """Emulate JavaScript ``| 0`` — coerce to signed 32-bit integer."""
    n = n & 0xFFFFFFFF
    if n >= 0x80000000:
        n -= 0x100000000
    return n


def _imul(a: int, b: int) -> int:
    """Emulate ``Math.imul`` — 32-bit integer multiply (signed result)."""
    a &= 0xFFFFFFFF
    b &= 0xFFFFFFFF
    result = (a * b) & 0xFFFFFFFF
    if result >= 0x80000000:
        result -= 0x100000000
    return result


# ─── PRNG ──────────────────────────────────────────────────────────────────

def _mulberry32(seed: int) -> Callable[[], float]:
    """Mulberry32 seeded PRNG — returns values in [0, 1).

    Matches the JavaScript implementation exactly::

        let a = seed >>> 0
        return function() {
            a |= 0; a = (a + 0x6d2b79f5) | 0
            let t = Math.imul(a ^ (a >>> 15), 1 | a)
            t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296
        }
    """
    state = [_to_uint32(seed)]

    def _next() -> float:
        a = _to_int32(state[0])
        a = _to_int32(a + 0x6D2B79F5)
        state[0] = _to_uint32(a)

        t = _imul(a ^ (_to_uint32(a) >> 15), _to_int32(1 | _to_uint32(a)))
        t = _to_int32(
            t + _imul(t ^ (_to_uint32(t) >> 7), _to_int32(61 | _to_uint32(t)))
        ) ^ t
        return _to_uint32(t ^ (_to_uint32(t) >> 14)) / 4294967296

    return _next


def _hash_string(s: str) -> int:
    """FNV-1a hash matching the non-Bun JavaScript path.

    ::

        let h = 2166136261
        for (let i = 0; i < s.length; i++) {
            h ^= s.charCodeAt(i)
            h = Math.imul(h, 16777619)
        }
        return h >>> 0
    """
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = _imul(h, 16777619)
    return _to_uint32(h)


# ─── Helpers ───────────────────────────────────────────────────────────────

def _pick(rng: Callable[[], float], arr: Sequence[T]) -> T:
    """Pick a random element from *arr* using *rng*."""
    return arr[int(math.floor(rng() * len(arr)))]


def _roll_rarity(rng: Callable[[], float]) -> str:
    """Weighted rarity selection."""
    total = sum(RARITY_WEIGHTS.values())
    roll = rng() * total
    for rarity in RARITIES:
        roll -= RARITY_WEIGHTS[rarity]
        if roll < 0:
            return rarity
    return "common"


_RARITY_FLOOR: Dict[str, int] = {
    "common": 5,
    "uncommon": 15,
    "rare": 25,
    "epic": 35,
    "legendary": 50,
}


def _roll_stats(rng: Callable[[], float], rarity: str) -> Dict[str, int]:
    """Roll stats — one peak, one dump, rest scattered. Rarity bumps floor."""
    floor = _RARITY_FLOOR[rarity]
    peak = _pick(rng, STAT_NAMES)
    dump = _pick(rng, STAT_NAMES)
    while dump == peak:
        dump = _pick(rng, STAT_NAMES)

    stats: Dict[str, int] = {}
    for name in STAT_NAMES:
        if name == peak:
            stats[name] = min(100, floor + 50 + int(math.floor(rng() * 30)))
        elif name == dump:
            stats[name] = max(1, floor - 10 + int(math.floor(rng() * 15)))
        else:
            stats[name] = floor + int(math.floor(rng() * 40))
    return stats


# ─── Public API ────────────────────────────────────────────────────────────

_SALT = "friend-2026-401"


@dataclass(frozen=True)
class Roll:
    """Result of rolling a companion — deterministic bones + inspiration seed."""

    bones: CompanionBones
    inspiration_seed: int


def _roll_from(rng: Callable[[], float]) -> Roll:
    """Generate a full Roll from a seeded PRNG."""
    rarity = _roll_rarity(rng)
    bones = CompanionBones(
        rarity=rarity,
        species=_pick(rng, SPECIES),
        eye=_pick(rng, EYES),
        hat="none" if rarity == "common" else _pick(rng, HATS),
        shiny=rng() < 0.01,
        stats=_roll_stats(rng, rarity),
    )
    return Roll(bones=bones, inspiration_seed=int(math.floor(rng() * 1e9)))


# Simple one-entry cache matching the TS implementation.
_roll_cache: Dict[str, Roll] = {}


def roll(user_id: str) -> Roll:
    """Generate deterministic companion bones from a user ID.

    Results are cached per ``user_id`` to avoid redundant computation on
    hot paths (sprite ticks, prompt input, per-turn observer).
    """
    key = user_id + _SALT
    if key in _roll_cache:
        return _roll_cache[key]
    value = _roll_from(_mulberry32(_hash_string(key)))
    # Keep cache at one entry like the TS version.
    _roll_cache.clear()
    _roll_cache[key] = value
    return value


def roll_with_seed(seed: str) -> Roll:
    """Generate companion bones from an arbitrary seed string."""
    return _roll_from(_mulberry32(_hash_string(seed)))
