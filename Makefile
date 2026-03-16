PYTHON ?= python3
PROJECT_ROOT := $(CURDIR)
SKILL_DIR := $(PROJECT_ROOT)/skills/pdf-to-structured-markdown
SCRIPTS_DIR := $(SKILL_DIR)/scripts
WHY_ETHICS_BUNDLE := $(PROJECT_ROOT)/generated/why-ethics
WHY_ETHICS_GATE_CONFIG := $(SKILL_DIR)/references/why-ethics-quality-gate.json
CHALLENGE_CONFIG := $(SKILL_DIR)/references/challenge-corpus.json
BENCHMARK_JSON := $(SKILL_DIR)/references/why-ethics-retrieval-benchmark.json
GATE_ARGS ?=
SMOKE_ARGS ?=
COMPARE_BACKENDS_ARGS ?=

.PHONY: bootstrap doctor status test-fast test gate smoke compare-backends map verify-all

bootstrap:
	$(PYTHON) -m pip install -e .

doctor:
	$(PYTHON) $(SCRIPTS_DIR)/doctor.py

status:
	$(PYTHON) $(SCRIPTS_DIR)/status_snapshot.py

test-fast:
	$(PYTHON) -m compileall -q $(SCRIPTS_DIR) src/pdfmd
	$(PYTHON) -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_project_ops.py' -v
	$(PYTHON) -m unittest discover -s skills/pdf-to-structured-markdown/tests -p 'test_wrapper_parity.py' -v

test:
	$(PYTHON) -m unittest discover -s skills/pdf-to-structured-markdown/tests -v

gate:
	$(PYTHON) $(SCRIPTS_DIR)/run_quality_gate.py $(WHY_ETHICS_BUNDLE) $(WHY_ETHICS_GATE_CONFIG) $(GATE_ARGS)

smoke:
	$(PYTHON) $(SCRIPTS_DIR)/run_challenge_corpus.py $(CHALLENGE_CONFIG) --skip-convert $(SMOKE_ARGS)

compare-backends:
	$(PYTHON) $(SCRIPTS_DIR)/compare_embedding_backends.py $(WHY_ETHICS_BUNDLE) $(BENCHMARK_JSON) --dry-run $(COMPARE_BACKENDS_ARGS)

map:
	@if command -v codex >/dev/null 2>&1; then \
		codex exec 'Run $$gsdr-map-codebase to refresh .planning/codebase for /Users/rookslog/Projects/PDFAgentialConversion'; \
	else \
		echo "codex command not found; install Codex CLI/app support before using make map"; \
		exit 1; \
	fi

verify-all: test-fast test smoke compare-backends gate
