# Aura — Human Intelligence Engine

## Quick start
make install && make test

## Architecture
- src/aura/core/ — readiness engine, conversation processor, self-model
- src/aura/cli/ — terminal UI, brand system, companion sprites
- src/aura/bridge/ — Buddy<>Aura signal bridge (JSON files)
- src/aura/transport/ — real-time WebSocket transport (optional)
- src/aura/protocol/ — NDJSON message protocol
- src/aura/persistence/ — session history, atomic writes
- sidecar/ — Node.js WebSocket bridge (optional, for remote mode)

## Testing
pytest tests/ — 500+ tests, all stdlib, ~2s

## Key commands
aura              # Interactive CLI
aura --remote     # Enable WebSocket transport
aura --serve      # Headless multi-session server
aura --demo       # Demo scenario

## Development
- Zero required dependencies (stdlib only) — this is intentional
- Optional deps: `pip install -e ".[dev]"` for pytest/ruff, `.[ml]` for ML features
- Sidecar requires Node.js: `cd sidecar && npm install && npm run build`
