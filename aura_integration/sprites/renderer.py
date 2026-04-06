"""Sprite rendering — ASCII art assembly with eye substitution, hats, and color.

Provides the visual output layer for the companion sprite system:
- ``render_sprite``  renders a plain-text sprite frame
- ``render_face``    returns a compact one-line face string per species
- ``render_sprite_colored``  wraps output in ANSI 24-bit color escapes
  using Aura's brand theme system

Ported from the TypeScript ``sprites.ts`` renderer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from src.aura.cli.sprites.bodies import BODIES, HAT_LINES
from src.aura.cli.sprites.types import RARITY_COLORS, CompanionBones

if TYPE_CHECKING:
    from src.aura.cli.brand import AuraTheme


# ─── Plain Rendering ──────────────────────────────────────────────────────

def render_sprite(bones: CompanionBones, frame: int = 0) -> List[str]:
    """Render a single animation frame for *bones* as a list of strings.

    Eye placeholders (``{E}``) are replaced with the companion's eye
    character.  Hat overlays are applied to line 0 when the hat slot is
    blank.  A blank hat-slot row is dropped when *all* frames for the
    species have a blank first line (avoids height oscillation).
    """
    frames = BODIES[bones.species]
    body = [line.replace("{E}", bones.eye) for line in frames[frame % len(frames)]]
    lines = list(body)

    # Only overlay hat when line 0 is empty (some fidget frames use it
    # for smoke / antenna effects).
    if bones.hat != "none" and not lines[0].strip():
        lines[0] = HAT_LINES[bones.hat]

    # Drop blank hat slot to save vertical space — but only when ALL
    # frames have a blank first line so heights don't oscillate.
    if not lines[0].strip() and all(not f[0].strip() for f in frames):
        lines.pop(0)

    return lines


def sprite_frame_count(species: str) -> int:
    """Return the number of animation frames for *species*."""
    return len(BODIES[species])


def render_face(bones: CompanionBones) -> str:
    """Return a compact one-line face string for *bones*.

    Useful for inline display in prompts, status bars, and chat headers.
    """
    e = bones.eye
    species = bones.species

    face_map = {
        "duck": f"({e}>",
        "goose": f"({e}>",
        "blob": f"({e}{e})",
        "cat": f"={e}\u03c9{e}=",
        "dragon": f"<{e}~{e}>",
        "octopus": f"~({e}{e})~",
        "owl": f"({e})({e})",
        "penguin": f"({e}>)",
        "turtle": f"[{e}_{e}]",
        "snail": f"{e}(@)",
        "ghost": f"/{e}{e}\\",
        "axolotl": f"}}{e}.{e}{{",
        "capybara": f"({e}oo{e})",
        "cactus": f"|{e}  {e}|",
        "robot": f"[{e}{e}]",
        "rabbit": f"({e}..{e})",
        "mushroom": f"|{e}  {e}|",
        "chonk": f"({e}.{e})",
    }
    return face_map.get(species, f"({e}{e})")


# ─── Colored Rendering ────────────────────────────────────────────────────

def render_sprite_colored(
    bones: CompanionBones,
    frame: int = 0,
    theme: Optional[AuraTheme] = None,
) -> List[str]:
    """Render a sprite frame wrapped in ANSI color escapes.

    The color is chosen from the Aura theme based on companion rarity:

    - common    -> ``text_dim``
    - uncommon  -> ``success``
    - rare      -> ``info``
    - epic      -> ``accent``
    - legendary -> ``warning``

    If *theme* is ``None`` the plain (uncolored) sprite is returned.
    """
    lines = render_sprite(bones, frame)

    if theme is None:
        return lines

    color_name = RARITY_COLORS.get(bones.rarity, "text_dim")
    fg_code = theme.fg(color_name)
    reset = "\033[0m"

    return [f"{fg_code}{line}{reset}" for line in lines]
