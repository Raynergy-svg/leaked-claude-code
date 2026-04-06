# How to apply Phases 1-5 to the Aura repo

The integration code was built directly in the Aura repo on branch
`claude/integrate-code-project-dXmvZ`. It sits on top of the latest
`main` (including Phases 20-25).

## Option A: Cherry-pick from this repo's aura_integration/ directory

The `aura_integration/` directory in the `claude/integrate-code-project-dXmvZ`
branch contains all source files organized by module. Copy them into Aura:

```bash
cd /path/to/Aura

# Protocol module
mkdir -p src/aura/protocol
cp aura_integration/protocol/*.py src/aura/protocol/

# Sprite system  
mkdir -p src/aura/cli/sprites
cp aura_integration/sprites/*.py src/aura/cli/sprites/

# Persistence (convert persistence.py to package)
mv src/aura/persistence.py src/aura/persistence/atomic.py
mkdir -p src/aura/persistence
cp aura_integration/persistence/*.py src/aura/persistence/

# Transport layer
mkdir -p src/aura/transport
cp aura_integration/transport/*.py src/aura/transport/

# Sidecar
mkdir -p sidecar/src
cp aura_integration/sidecar/package.json sidecar/
cp aura_integration/sidecar/src/*.ts sidecar/src/

# Tests
cp aura_integration/tests/*.py tests/

# Portability
cp aura_integration/Makefile aura_integration/CLAUDE.md .
cp aura_integration/requirements*.txt .
mkdir -p .github/workflows
cp aura_integration/.github/workflows/test.yml .github/workflows/

# Apply patches to modified files
git apply aura_integration/companion_integration.patch
git apply aura_integration/companion_history.patch
git apply aura_integration/main_remote_flag.patch
git apply aura_integration/main_serve_flag.patch
```

## Option B: If you have the Claude Code session environment

The Aura repo at `/home/user/Aura` already has everything on branch
`claude/integrate-code-project-dXmvZ`. Just push it:

```bash
cd /home/user/Aura
git checkout claude/integrate-code-project-dXmvZ
git push origin claude/integrate-code-project-dXmvZ
```

Then create a PR from that branch into main.

## What's included

| Phase | Module | Files | Tests |
|-------|--------|-------|-------|
| 1 | src/aura/protocol/ | 5 | 19 |
| 2 | sidecar/ + src/aura/transport/ | 5 TS + 3 py | 15 |
| 3 | src/aura/cli/sprites/ | 5 | 33 |
| 4 | src/aura/persistence/ | 5 | 53 |
| 5 | src/aura/transport/session_manager.py | 1 + portability | 15 |
| **Total** | | **34 files** | **135 tests** |

All 135 tests pass. Zero new required dependencies.
