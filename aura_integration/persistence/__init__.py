"""Persistence package — atomic writes, session history, and session indexing.

Re-exports atomic_write and atomic_write_json from the atomic module so that
existing imports (e.g. ``from src.aura.persistence import atomic_write_json``)
continue to work after the module-to-package conversion.
"""

from src.aura.persistence.atomic import atomic_write, atomic_write_json, _HAS_FCNTL

__all__ = ["atomic_write", "atomic_write_json", "_HAS_FCNTL"]
