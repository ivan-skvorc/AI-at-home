# DeerFlow - Unified Development Environment

.PHONY: help config config-upgrade check install setup doctor support-bundle detect-thread-boundaries detect-blocking-io dev dev-daemon start start-daemon nginx stop up up-start down clean docker-init docker-start docker-stop docker-logs docker-logs-frontend docker-logs-gateway docker-logs-redis searxng searxng-stop sandbox-up sandbox-down sandbox-logs sandbox-enable sandbox-disable fetch-browser auto-update auto-update-install auto-update-uninstall

# docker compose shim: prefer the v2 plugin, fall back to legacy docker-compose.
DOCKER_COMPOSE ?= docker compose
SANDBOX_COMPOSE_FILE = docker/docker-compose.sandbox.yml

BASH ?= bash
BACKEND_UV_RUN = cd backend && uv run

# Detect OS for Windows compatibility
ifeq ($(OS),Windows_NT)
    SHELL := cmd.exe
    PYTHON ?= python
    # Run repo shell scripts through Git Bash when Make is launched from cmd.exe / PowerShell.
    RUN_WITH_GIT_BASH = call scripts\run-with-git-bash.cmd
else
    PYTHON ?= python3
    RUN_WITH_GIT_BASH =
endif

FRONTEND_PNPM = $(PYTHON) ../scripts/pnpm.py

help:
	@echo "DeerFlow Development Commands:"
	@echo "  make setup           - Interactive setup wizard (recommended for new users)"
	@echo "  make doctor          - Check configuration and system requirements"
	@echo "  make support-bundle  - Create a redacted issue summary, AI draft, and evidence bundle"
	@echo "  make config          - Generate local config files (aborts if config already exists)"
	@echo "  make config-upgrade  - Merge new fields from config.example.yaml into config.yaml"
	@echo "  make check           - Check if all required tools are installed"
	@echo "  make detect-thread-boundaries - Inventory backend executor/thread/event-loop boundaries"
	@echo "  make detect-blocking-io        - Inventory blocking IO that may block the backend event loop"
	@echo "  make install         - Install all dependencies (frontend + backend + pre-commit hooks)"
	@echo "  make setup-sandbox   - Pre-pull sandbox container image (recommended)"
	@echo "  make sandbox-enable  - Switch config.yaml to the containerized AIO sandbox"
	@echo "  make sandbox-disable - Switch config.yaml back to the local sandbox"
	@echo "  make sandbox-up      - Start the standalone AIO sandbox container (localhost:8091)"
	@echo "  make sandbox-down    - Stop and remove the AIO sandbox container"
	@echo "  make sandbox-logs    - Follow the AIO sandbox container logs"
	@echo "  make fetch-browser   - Download the Camoufox browser for the local web_fetch backend"
	@echo "  make auto-update     - Update the Camoufox browser + bundled SearXNG image now"
	@echo "  make auto-update-install   - Install a daily systemd timer for the update above"
	@echo "  make auto-update-uninstall - Remove the daily auto-update timer"
	@echo "  make dev             - Start all services in development mode (with hot-reloading)"
	@echo "  make searxng         - Start only the SearXNG search container (launch paths auto-start it when needed)"
	@echo "  make searxng-stop    - Stop the standalone SearXNG search container"
	@echo "  make dev-daemon      - Start dev services in background (daemon mode)"
	@echo "  make start           - Start all services in production mode (optimized, no hot-reloading)"
	@echo "  make start-daemon    - Start prod services in background (daemon mode)"
	@echo "  make nginx           - Start nginx alone in the foreground (local dev config)"
	@echo "  make stop            - Stop all running services"
	@echo "  make clean           - Clean up processes and temporary files"
	@echo ""
	@echo "Docker Production Commands:"
	@echo "  make up              - Build and start production Docker services (localhost:2026)"
	@echo "  make up-start        - Start production services from pre-built images (apply .env/config-only changes, no rebuild)"
	@echo "  make down            - Stop and remove production Docker containers"
	@echo ""
	@echo "Docker Development Commands:"
	@echo "  make docker-init     - Pull the sandbox image"
	@echo "  make docker-start    - Start Docker services (mode-aware from config.yaml, localhost:2026)"
	@echo "  make docker-stop     - Stop Docker development services"
	@echo "  make docker-logs     - View Docker development logs"
	@echo "  make docker-logs-frontend - View Docker frontend logs"
	@echo "  make docker-logs-gateway - View Docker gateway logs"
	@echo "  make docker-logs-redis - View Docker Redis logs"

## Setup & Diagnosis
setup:
	@$(BACKEND_UV_RUN) python ../scripts/setup_wizard.py

doctor:
	@$(BACKEND_UV_RUN) python ../scripts/doctor.py

support-bundle:
	@$(BACKEND_UV_RUN) python ../scripts/support_bundle.py --include-doctor

detect-thread-boundaries:
	@$(BACKEND_UV_RUN) python ../scripts/detect_thread_boundaries.py --json-output ../.deer-flow/thread-boundary-inventory.json

detect-blocking-io:
	@$(MAKE) -C backend detect-blocking-io

config:
	@$(PYTHON) ./scripts/configure.py

config-upgrade:
	@$(RUN_WITH_GIT_BASH) ./scripts/config-upgrade.sh

# Check required tools
check:
	@$(PYTHON) ./scripts/check.py

# Install all dependencies
install:
	@echo "Installing backend dependencies..."
	@cd backend && uv sync
	@echo "Installing frontend dependencies..."
	@cd frontend && $(FRONTEND_PNPM) install
	@echo "Installing pre-commit hooks..."
	@uv tool install pre-commit
	@pre-commit install --overwrite
	@echo "✓ All dependencies installed"
	@echo ""
	@echo "=========================================="
	@echo "  Optional: Pre-pull Sandbox Image"
	@echo "=========================================="
	@echo ""
	@echo "If you plan to use Docker/Container-based sandbox, you can pre-pull the image:"
	@echo "  make setup-sandbox"
	@echo ""

# Pre-pull sandbox Docker image (optional but recommended)
setup-sandbox:
	@$(RUN_WITH_GIT_BASH) ./scripts/setup-sandbox.sh

# Switch config.yaml between the local and containerized AIO sandbox (rewrites
# only the sandbox: section, backs up to config.yaml.bak, preserves environment:).
# MODE=external (default): one shared container managed by `make sandbox-up`.
# MODE=container: per-thread containers with host-backed /mnt/user-data mounts —
# the mode to use for clone-and-debug workflows (`make sandbox-enable MODE=container`).
SANDBOX_MODE ?= $(or $(MODE),external)
sandbox-enable:
	@$(BACKEND_UV_RUN) python ../scripts/sandbox_toggle.py enable --mode $(SANDBOX_MODE)

sandbox-disable:
	@$(BACKEND_UV_RUN) python ../scripts/sandbox_toggle.py disable

# Standalone AIO sandbox container (docker/docker-compose.sandbox.yml).
# `make dev` auto-starts it when config selects base_url and it is unreachable;
# these targets give manual control. Lifecycle is yours — dev never destroys it.
sandbox-up:
	$(DOCKER_COMPOSE) -f $(SANDBOX_COMPOSE_FILE) up -d

sandbox-down:
	$(DOCKER_COMPOSE) -f $(SANDBOX_COMPOSE_FILE) down

sandbox-logs:
	$(DOCKER_COMPOSE) -f $(SANDBOX_COMPOSE_FILE) logs --tail=100 -f

# Manually pre-download the Camoufox browser binaries for the web_fetch backend.
# Large download — only relevant when tools.web_fetch backend is set to camoufox.
# Both the python package AND these browser binaries install automatically on
# every launch path (make dev/start, docker-start, up) once camoufox is selected
# (scripts/ensure_camoufox.py + the Dockerfile bake); this target is a manual
# pre-fetch for when you want the download to happen ahead of first launch.
fetch-browser:
	@$(BACKEND_UV_RUN) python -m camoufox fetch

# Refresh the two components this repo installs itself — the Camoufox browser
# binaries and the bundled SearXNG :latest image — neither of which self-updates
# after first install. Idempotent + best-effort (no-op when a component isn't in
# use or is already current). Runs inside the backend venv so camoufox imports.
auto-update:
	@$(BACKEND_UV_RUN) python ../scripts/update_camoufox_searxng.py --verbose

# Install / remove a daily `systemd --user` timer that runs `make auto-update`
# even when the app isn't launched (the local launch paths also run it, throttled
# to once a day). Prints an equivalent cron line where systemd --user is absent.
auto-update-install:
	@$(PYTHON) ./scripts/install_auto_update.py

auto-update-uninstall:
	@$(PYTHON) ./scripts/install_auto_update.py --uninstall

# Start all services in development mode (with hot-reloading)
# Ollama auto-populate + Camoufox browser fetch run inside scripts/serve.sh so
# every local launch path (dev/start, foreground/daemon) shares one code path.
dev:
	@$(PYTHON) ./scripts/check.py
	@mkdir -p .deer-flow/nginx-tmp
	@$(RUN_WITH_GIT_BASH) ./scripts/serve.sh --dev

# Start all services in production mode (with optimizations)
start:
	@$(PYTHON) ./scripts/check.py
	@$(RUN_WITH_GIT_BASH) ./scripts/serve.sh --prod

# Start all services in daemon mode (background)
dev-daemon:
	@$(PYTHON) ./scripts/check.py
	@$(RUN_WITH_GIT_BASH) ./scripts/serve.sh --dev --daemon

# Start prod services in daemon mode (background)
start-daemon:
	@$(PYTHON) ./scripts/check.py
	@$(RUN_WITH_GIT_BASH) ./scripts/serve.sh --prod --daemon

# Start nginx alone in the foreground with the local dev config
nginx:
	@$(RUN_WITH_GIT_BASH) ./scripts/nginx.sh

# Stop all services
stop:
	@$(RUN_WITH_GIT_BASH) ./scripts/serve.sh --stop

# Clean up
clean: stop
	@echo "Cleaning up..."
	@-rm -rf backend/.deer-flow 2>/dev/null || true
	@-rm -rf logs/*.log 2>/dev/null || true
	@echo "✓ Cleanup complete"

# ==========================================
# Docker Development Commands
# ==========================================

# Initialize Docker containers and install dependencies
docker-init:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh init

# Start Docker development environment
docker-start:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh start

# Stop Docker development environment
docker-stop:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh stop

# View Docker development logs
docker-logs:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh logs

# View Docker development logs
docker-logs-frontend:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh logs --frontend
docker-logs-gateway:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh logs --gateway
docker-logs-redis:
	@$(RUN_WITH_GIT_BASH) ./scripts/docker.sh logs --redis

# ==========================================
# Production Docker Commands
# ==========================================

# Build and start production services
up:
	@$(RUN_WITH_GIT_BASH) ./scripts/deploy.sh

# Start production services from pre-built images (no rebuild). Use this to apply
# config-only changes (e.g. BIND_HOST / PORT in .env) without the slow image rebuild.
up-start:
	@$(RUN_WITH_GIT_BASH) ./scripts/deploy.sh start

# Stop and remove production containers
down:
	@$(RUN_WITH_GIT_BASH) ./scripts/deploy.sh down

# Start only the SearXNG search container (backs the default web_search tool).
# All launch paths (make up / make docker-start / make dev / make start) already
# auto-detect or auto-start it via scripts/detect_searxng.py; this target is for
# manual control. Publishes 127.0.0.1:8088 to match config.yaml's default base_url.
searxng:
	@$(RUN_WITH_GIT_BASH) ./scripts/searxng.sh up

searxng-stop:
	@$(RUN_WITH_GIT_BASH) ./scripts/searxng.sh stop
