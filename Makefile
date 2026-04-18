PYTHON ?= $(if $(wildcard ./venv/bin/python),./venv/bin/python,python3)
GRAPH_PYTHON ?= python3
GRAPH_BUILDER_DIR := graph-builder
GRAPH_SCRIPT := $(GRAPH_BUILDER_DIR)/build_code_graph.py
OPEN_OBSIDIAN_SCRIPT := $(GRAPH_BUILDER_DIR)/open_obsidian.py
SOURCE_ROOT := .
GRAPH_JSON := graphify-out/graph.json
GRAPH_HTML := graphify-out/graph.html
GRAPH_REPORT := graphify-out/GRAPH_REPORT.md
GRAPH_WIKI_INDEX := graphify-out/wiki/index.md
OBSIDIAN_VAULT := $(HOME)/vault/graphify/xcg-bot

.PHONY: help run test graph graph-build graph-no-obsidian validate-graph clean-graph show-graph-paths

help:
	@printf "Targets:\n"
	@printf "  make run   - start the Discord bot\n"
	@printf "  make test  - run unit tests\n"
	@printf "  make graph - rebuild the code graph and open the Obsidian vault\n"

run:
	$(PYTHON) main.py

test:
	$(PYTHON) -m unittest -q tests.test_xcg_bot

graph: graph-build
	$(GRAPH_PYTHON) $(OPEN_OBSIDIAN_SCRIPT) "$(OBSIDIAN_VAULT)"

graph-build:
	$(GRAPH_PYTHON) $(GRAPH_SCRIPT) --source-root "$(SOURCE_ROOT)"

graph-no-obsidian:
	$(GRAPH_PYTHON) $(GRAPH_SCRIPT) --source-root "$(SOURCE_ROOT)" --skip-obsidian

validate-graph:
	$(GRAPH_PYTHON) $(GRAPH_SCRIPT) --source-root "$(SOURCE_ROOT)" --validate-only

clean-graph:
	rm -rf graphify-out

show-graph-paths:
	@printf '%s\n' "$(GRAPH_JSON)" "$(GRAPH_HTML)" "$(GRAPH_REPORT)" "$(GRAPH_WIKI_INDEX)"
