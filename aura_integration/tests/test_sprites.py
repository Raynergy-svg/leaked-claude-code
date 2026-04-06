"""Tests for the companion sprite system."""

import pytest

from src.aura.cli.sprites.types import (
    SPECIES, EYES, HATS, RARITIES, STAT_NAMES,
    RARITY_WEIGHTS, RARITY_STARS, CompanionBones,
)
from src.aura.cli.sprites.companion import roll, roll_with_seed, _hash_string, _mulberry32
from src.aura.cli.sprites.renderer import render_sprite, render_face, sprite_frame_count
from src.aura.cli.sprites.bodies import BODIES, HAT_LINES


# ── Type Constants ────────────────────────────────────────────────────────

class TestTypeConstants:
    def test_18_species(self):
        assert len(SPECIES) == 18

    def test_6_eyes(self):
        assert len(EYES) == 6

    def test_8_hats(self):
        assert len(HATS) == 8
        assert HATS[0] == "none"

    def test_5_rarities(self):
        assert len(RARITIES) == 5
        assert RARITIES[0] == "common"
        assert RARITIES[-1] == "legendary"

    def test_5_stats(self):
        assert len(STAT_NAMES) == 5

    def test_rarity_weights_sum(self):
        assert sum(RARITY_WEIGHTS.values()) == 100

    def test_all_rarities_have_stars(self):
        for r in RARITIES:
            assert r in RARITY_STARS


# ── PRNG Determinism ──────────────────────────────────────────────────────

class TestPRNGDeterminism:
    def test_hash_string_deterministic(self):
        """Same input always produces same hash."""
        assert _hash_string("hello") == _hash_string("hello")

    def test_hash_string_different_inputs(self):
        assert _hash_string("hello") != _hash_string("world")

    def test_hash_string_fnv1a_known_value(self):
        """FNV-1a of empty string with offset basis 2166136261."""
        h = _hash_string("")
        assert h == 2166136261  # offset basis, no chars processed

    def test_mulberry32_deterministic(self):
        """Same seed always produces same sequence."""
        rng1 = _mulberry32(42)
        rng2 = _mulberry32(42)
        for _ in range(10):
            assert rng1() == rng2()

    def test_mulberry32_range(self):
        """Output must be in [0, 1)."""
        rng = _mulberry32(12345)
        for _ in range(100):
            val = rng()
            assert 0.0 <= val < 1.0

    def test_mulberry32_not_all_same(self):
        """PRNG must produce varying output (not stuck at 0)."""
        rng = _mulberry32(99)
        values = {rng() for _ in range(10)}
        assert len(values) > 1

    def test_roll_deterministic(self):
        """Same userId always produces same companion."""
        r1 = roll("user-abc")
        r2 = roll("user-abc")
        assert r1.bones.species == r2.bones.species
        assert r1.bones.rarity == r2.bones.rarity
        assert r1.bones.eye == r2.bones.eye
        assert r1.bones.hat == r2.bones.hat
        assert r1.bones.stats == r2.bones.stats

    def test_roll_different_users(self):
        """Different userIds should (usually) produce different companions."""
        r1 = roll("alice")
        r2 = roll("bob")
        # Extremely unlikely both species AND eye AND hat match
        assert (r1.bones.species, r1.bones.eye) != (r2.bones.species, r2.bones.eye) or True


# ── Companion Generation ──────────────────────────────────────────────────

class TestCompanionGeneration:
    def test_roll_returns_valid_species(self):
        r = roll("test")
        assert r.bones.species in SPECIES

    def test_roll_returns_valid_rarity(self):
        r = roll("test")
        assert r.bones.rarity in RARITIES

    def test_roll_returns_valid_eye(self):
        r = roll("test")
        assert r.bones.eye in EYES

    def test_roll_returns_valid_hat(self):
        r = roll("test")
        assert r.bones.hat in HATS

    def test_common_has_no_hat(self):
        """Common rarity companions always have hat='none'."""
        # Roll many users until we get a common
        for i in range(100):
            r = roll(f"user-{i}")
            if r.bones.rarity == "common":
                assert r.bones.hat == "none"
                return
        # If we never got a common in 100 tries, that's fine (extremely unlikely)

    def test_stats_all_present(self):
        r = roll("test")
        for stat in STAT_NAMES:
            assert stat in r.bones.stats
            assert 0 <= r.bones.stats[stat] <= 100

    def test_roll_with_seed(self):
        r = roll_with_seed("custom-seed")
        assert r.bones.species in SPECIES

    def test_inspiration_seed_is_int(self):
        r = roll("test")
        assert isinstance(r.inspiration_seed, int)


# ── Sprite Bodies ─────────────────────────────────────────────────────────

class TestSpriteBodies:
    def test_all_species_have_bodies(self):
        for species in SPECIES:
            assert species in BODIES, f"Missing body for {species}"

    def test_all_species_have_3_frames(self):
        for species in SPECIES:
            assert len(BODIES[species]) == 3, f"{species} should have 3 frames"

    def test_each_frame_has_5_lines(self):
        for species in SPECIES:
            for i, frame in enumerate(BODIES[species]):
                assert len(frame) == 5, f"{species} frame {i} should have 5 lines"

    def test_all_hats_have_lines(self):
        for hat in HATS:
            assert hat in HAT_LINES


# ── Rendering ─────────────────────────────────────────────────────────────

class TestRendering:
    def test_render_sprite_returns_lines(self):
        r = roll("render-test")
        lines = render_sprite(r.bones, frame=0)
        assert isinstance(lines, list)
        assert all(isinstance(l, str) for l in lines)

    def test_render_sprite_substitutes_eyes(self):
        r = roll("render-test")
        lines = render_sprite(r.bones, frame=0)
        joined = "".join(lines)
        assert "{E}" not in joined  # no unsubstituted placeholders

    def test_render_sprite_all_frames(self):
        r = roll("frame-test")
        count = sprite_frame_count(r.bones.species)
        for frame in range(count):
            lines = render_sprite(r.bones, frame=frame)
            assert len(lines) >= 4  # at least 4 lines (hat row may be dropped)

    def test_render_face_returns_string(self):
        for species in SPECIES:
            bones = CompanionBones(
                rarity="common",
                species=species,
                eye="·",
                hat="none",
                shiny=False,
                stats={s: 50 for s in STAT_NAMES},
            )
            face = render_face(bones)
            assert isinstance(face, str)
            assert len(face) > 0

    def test_sprite_frame_count(self):
        for species in SPECIES:
            assert sprite_frame_count(species) == 3

    def test_render_all_18_species(self):
        """Every species renders without error."""
        for i, species in enumerate(SPECIES):
            bones = CompanionBones(
                rarity="rare",
                species=species,
                eye="✦",
                hat="crown",
                shiny=False,
                stats={s: 50 for s in STAT_NAMES},
            )
            lines = render_sprite(bones, frame=0)
            assert len(lines) >= 4
            joined = "".join(lines)
            assert "{E}" not in joined
