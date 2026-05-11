HOST ?= 100.72.248.102
PORT ?= 8013
PYTHON ?= ../.venv/bin/python
PID_FILE ?= .internal-server.pid

.PHONY: online build stop status

build:
	cd app && npm install
	cd app && npm run build

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

online: build stop
	@echo "Starting internal tools at http://$(HOST):$(PORT)/"
	@setsid env INTERNAL_HTMLS_HOST="$(HOST)" INTERNAL_HTMLS_PORT="$(PORT)" "$(PYTHON)" server.py > internal-server.log 2>&1 & echo $$! > "$(PID_FILE)"
	@sleep 1
	@if ! kill -0 "$$(cat "$(PID_FILE)")" 2>/dev/null; then \
		echo "Server failed to start. Last log lines:"; \
		tail -40 internal-server.log; \
		exit 1; \
	fi
	@echo "PID $$(cat "$(PID_FILE)")"
	@echo "Log: internal-htmls/internal-server.log"
	@echo "Home:            http://$(HOST):$(PORT)/"
	@echo "Task Creator:    http://$(HOST):$(PORT)/task-creator"
	@echo "OKR Creator:     http://$(HOST):$(PORT)/okr-creator"
	@echo "Meeting Creator: http://$(HOST):$(PORT)/meeting-creator"
	@echo "Log Creator:     http://$(HOST):$(PORT)/log-creator"

status:
	@ss -ltnp | grep ":$(PORT)" || true
