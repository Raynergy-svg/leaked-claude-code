"""Aura Companion Sprite System — visual companion sprites for the CLI.

Ported from Claude Code's buddy system (TypeScript) as Phase 3 of
capability integration into Aura.

Public API:
    roll(user_id)           -> Roll (bones + inspiration_seed)
    render_sprite(bones)    -> list[str]  (ASCII art lines)
    render_face(bones)      -> str        (compact face string)
    render_sprite_colored() -> list[str]  (ANSI-colored sprite)
"""

from src.aura.cli.sprites.companion import roll, roll_with_seed, Roll
from src.aura.cli.sprites.renderer import (
    render_face,
    render_sprite,
    render_sprite_colored,
    sprite_frame_count,
)
from src.aura.cli.sprites.types import (
    EYES,
    HATS,
    RARITIES,
    RARITY_STARS,
    RARITY_WEIGHTS,
    SPECIES,
    STAT_NAMES,
    CompanionBones,
    CompanionSoul,
    StoredCompanion,
)

__all__ = [
    "roll",
    "roll_with_seed",
    "Roll",
    "render_face",
    "render_sprite",
    "render_sprite_colored",
    "sprite_frame_count",
    "EYES",
    "HATS",
    "RARITIES",
    "RARITY_STARS",
    "RARITY_WEIGHTS",
    "SPECIES",
    "STAT_NAMES",
    "CompanionBones",
    "CompanionSoul",
    "StoredCompanion",
]
