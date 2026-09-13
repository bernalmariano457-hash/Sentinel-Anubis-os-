.PHONY: install install-dev install-uconsole install-termux \
        test test-all test-hardware test-cov \
        lint format typecheck check \
        clean clean-pyc run help

PYTHON   := python3
PIP      := pip
PYTEST   := pytest
RUFF     := ruff
PYRIGHT  := pyright

WORK_DIRS := data/logs data/evidence/rf data/evidence/mobile \
             core/data/logs core/data/security plugins


install:
	@chmod +x install.sh && ./install.sh

install-dev:
	$(PIP) install -e ".[all]" --quiet
	$(PIP) install numpy scipy sounddevice --quiet
	@$(MAKE) _dirs
	@echo "✓ Entorno de desarrollo listo"

install-uconsole:
	$(PIP) install -e ".[uconsole]" --quiet
	@$(MAKE) _dirs

install-termux:
	$(PIP) install -e ".[termux]" --break-system-packages --quiet
	@$(MAKE) _dirs

_dirs:
	@mkdir -p $(WORK_DIRS)



test:
	$(PYTEST) \
		test_sentinel.py tools/test_sentinel.py tools/test_rfscanner.py \
		-m "not hardware and not root" \
		-k "not RealHardware" \
		--tb=short -q

test-cov:
	$(PYTEST) \
		test_sentinel.py tools/test_sentinel.py tools/test_rfscanner.py \
		-m "not hardware and not root" \
		-k "not RealHardware" \
		--cov=core --cov=modules \
		--cov-report=term-missing \
		--cov-report=html:htmlcov \
		-q
	@echo "→ Reporte HTML en htmlcov/index.html"

test-hardware:
	@echo "⚠ Requiere RTL-SDR conectado"
	$(PYTEST) \
		tools/test_rfscanner.py \
		-k "RealHardware" \
		-m "hardware" \
		--tb=short -v

test-all:
	$(PYTEST) \
		test_sentinel.py tools/test_sentinel.py tools/test_rfscanner.py \
		--tb=short -q

lint:
	$(RUFF) check . --output-format=concise

format:
	$(RUFF) check . --fix
	$(RUFF) format .

typecheck:
	$(PYRIGHT) --warnings

check: lint typecheck test
	@echo "✓ Todo en orden — el CI pasará"



run:
	$(PYTHON) Main.py


clean-pyc:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

clean: clean-pyc
	rm -rf .venv htmlcov .coverage coverage.xml dist build *.egg-info
	@echo "✓ Limpieza completa"



help:
	@echo ""
	@echo "  APEX SENTINEL — Makefile"
	@echo ""
	@grep -E '^## .+' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = "## "}; {printf "  \033[36m%-20s\033[0m %s\n", prev, $$2} {prev=$$1}' | \
		sed 's/^  Makefile://; s/^  //'
	@echo ""

.DEFAULT_GOAL := help
