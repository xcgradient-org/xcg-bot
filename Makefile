PYTHON ?= $(if $(wildcard ./.venv/bin/python),./.venv/bin/python,python3)
HOST ?= 100.72.248.102
PORT ?= 8013
PID_FILE ?= .internal-server.pid
LOG_FILE ?= internal-server.log

.PHONY: help run web online stop status bot build-frontend test

help:
	@printf "Targets:\n"
	@printf "  make web   - alias for make online\n"
	@printf "  make online - build frontend and start the internal website\n"
	@printf "  make stop  - stop the internal website\n"
	@printf "  make status - show what is listening on the internal port\n"
	@printf "  make bot   - start the Discord bot adapter\n"
	@printf "  make run   - alias for make bot\n"
	@printf "  make build-frontend - build the React frontend\n"
	@printf "  make test  - run unit tests\n"

run:
	$(PYTHON) -m bot.main

bot:
	$(PYTHON) -m bot.main

build-frontend:
	cd frontend && npm install
	cd frontend && npm run build

test:
	$(PYTHON) -m unittest -q backend.tests.test_xcg_bot

web: online

stop:
	@if [ -f "$(PID_FILE)" ]; then \
		pid=$$(cat "$(PID_FILE)"); \
		if kill -0 "$$pid" 2>/dev/null; then \
			echo "Stopping previous internal server $$pid"; \
			kill "$$pid"; \
			sleep 1; \
		fi; \
		rm -f "$(PID_FILE)"; \
	fi
	@if command -v fuser >/dev/null 2>&1; then \
		if fuser -n tcp "$(PORT)" >/dev/null 2>&1; then \
			echo "Stopping process(es) on port $(PORT)"; \
			fuser -k -n tcp "$(PORT)" >/dev/null 2>&1 || true; \
			sleep 1; \
		fi; \
	else \
		pids=$$(ss -ltnp 2>/dev/null | awk -v port=":$(PORT)" '$$4 ~ port "$$" && $$0 ~ /python/ { if (match($$0, /pid=[0-9]+/)) print substr($$0, RSTART+4, RLENGTH-4) }' | sort -u); \
		if [ -n "$$pids" ]; then \
			echo "Stopping process(es) on port $(PORT): $$pids"; \
			kill $$pids; \
			sleep 1; \
		fi; \
	fi

online: build-frontend stop
	@echo "Starting internal tools at http://$(HOST):$(PORT)/"
	@setsid env INTERNAL_HTMLS_HOST="$(HOST)" INTERNAL_HTMLS_PORT="$(PORT)" "$(PYTHON)" -m backend.app > "$(LOG_FILE)" 2>&1 & echo $$! > "$(PID_FILE)"
	@sleep 1
	@if ! kill -0 "$$(cat "$(PID_FILE)")" 2>/dev/null; then \
		echo "Server failed to start. Last log lines:"; \
		tail -40 "$(LOG_FILE)"; \
		exit 1; \
	fi
	@echo "PID $$(cat "$(PID_FILE)")"
	@echo "Log: $(LOG_FILE)"
	@echo "Home:            http://$(HOST):$(PORT)/"
	@echo "Task Creator:    http://$(HOST):$(PORT)/task-creator"
	@echo "OKR Creator:     http://$(HOST):$(PORT)/okr-creator"
	@echo "Meeting Creator: http://$(HOST):$(PORT)/meeting-creator"

status:
	@ss -ltnp | grep ":$(PORT)" || true
