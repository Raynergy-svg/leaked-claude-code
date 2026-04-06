.PHONY: install test test-quick lint build sidecar sidecar-install clean help

help:           ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install:        ## Install Aura (pip editable)
	pip install -e .

test:           ## Run all tests
	python -m pytest tests/ -v

test-quick:     ## Run tests (no slow tests)
	python -m pytest tests/ -x -q --timeout=10 2>/dev/null || python -m pytest tests/ -x -q

lint:           ## Check code style (if ruff available)
	@command -v ruff >/dev/null 2>&1 && ruff check src/ tests/ || echo "ruff not installed — skipping (pip install ruff)"

sidecar-install: ## Install sidecar deps
	cd sidecar && npm install

sidecar:        ## Build the Node.js sidecar
	cd sidecar && npm run build

clean:          ## Remove build artifacts
	rm -rf build/ dist/ *.egg-info src/*.egg-info .pytest_cache
	rm -rf sidecar/dist sidecar/node_modules
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
