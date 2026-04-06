"""Companion type definitions — rarities, species, accessories, and stats.

All constants are plain tuples/dicts for lightweight deterministic generation.
Dataclasses carry the structured companion data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ─── Constants ─────────────────────────────────────────────────────────────

RARITIES: Tuple[str, ...] = (
    "common",
    "uncommon",
    "rare",
    "epic",
    "legendary",
)

SPECIES: Tuple[str, ...] = (
    "duck",
    "goose",
    "blob",
    "cat",
    "dragon",
    "octopus",
    "owl",
    "penguin",
    "turtle",
    "snail",
    "ghost",
    "axolotl",
    "capybara",
    "cactus",
    "robot",
    "rabbit",
    "mushroom",
    "chonk",
)

EYES: Tuple[str, ...] = ("\u00b7", "\u2726", "\u00d7", "\u25c9", "@", "\u00b0")
#                          ·       ✦       ×       ◉      @    °

HATS: Tuple[str, ...] = (
    "none",
    "crown",
    "tophat",
    "propeller",
    "halo",
    "wizard",
    "beanie",
    "tinyduck",
)

STAT_NAMES: Tuple[str, ...] = (
    "DEBUGGING",
    "PATIENCE",
    "CHAOS",
    "WISDOM",
    "SNARK",
)

RARITY_WEIGHTS: Dict[str, int] = {
    "common": 60,
    "uncommon": 25,
    "rare": 10,
    "epic": 4,
    "legendary": 1,
}

RARITY_STARS: Dict[str, str] = {
    "common": "\u2605",
    "uncommon": "\u2605\u2605",
    "rare": "\u2605\u2605\u2605",
    "epic": "\u2605\u2605\u2605\u2605",
    "legendary": "\u2605\u2605\u2605\u2605\u2605",
}

# Maps rarity to Aura theme color names for render_sprite_colored.
RARITY_COLORS: Dict[str, str] = {
    "common": "text_dim",
    "uncommon": "success",
    "rare": "info",
    "epic": "accent",
    "legendary": "warning",
}


# ─── Data Classes ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CompanionBones:
    """Deterministic companion traits derived from hash(userId)."""

    rarity: str
    species: str
    eye: str
    hat: str
    shiny: bool
    stats: Dict[str, int]


@dataclass
class CompanionSoul:
    """Model-generated personality — persisted in config after first hatch."""

    name: str
    personality: str


@dataclass
class StoredCompanion:
    """What actually persists in config (soul + hatch timestamp)."""

    name: str
    personality: str
    hatched_at: float  # epoch seconds
