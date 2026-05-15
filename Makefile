# ══════════════════════════════════════════════════════════════════════
#  APEX SENTINEL — Makefile
#  Atajos para desarrollo local. Requiere .venv activo o instalar primero.
#
#  Uso rápido:
#    make install     → setup completo (primera vez)
#    make test        → correr tests sin hardware
#    make lint        → ruff + pyright
#    make check       → todo junto (lo que corre el CI)
# ══════════════════════════════════════════════════════════════════════

.PHONY: install install-dev install-uconsole install-termux \
        test test-all test-hardware test-cov \
        lint format typecheck check \
        clean clean-pyc run help

PYTHON   := python3
PIP      := pip
PYTEST   := pytest
RUFF     := ruff
PYRIGHT  := pyright

# Directorios de trabajo que deben existir
WORK_DIRS := data/logs data/evidence/rf data/evidence/mobile \
             core/data/logs core/data/security plugins


# ──────────────────────────────────────────────────────────────────────
# INSTALACIÓN
# ──────────────────────────────────────────────────────────────────────

## Instala el proyecto (auto-detect plataforma)
install:
	@chmod +x install.sh && ./install.sh

## Instala para desarrollo local (todos los extras + linters)
install-dev:
	$(PIP) install -e ".[all]" --quiet
	$(PIP) install numpy scipy sounddevice --quiet
	@$(MAKE) _dirs
	@echo "✓ Entorno de desarrollo listo"

## Instala para uConsole (network + RTL-SDR + ADS-B)
install-uconsole:
	$(PIP) install -e ".[uconsole]" --quiet
	@$(MAKE) _dirs

## Instala para Termux/Android
install-termux:
	$(PIP) install -e ".[termux]" --break-system-packages --quiet
	@$(MAKE) _dirs

# Crea directorios necesarios en silencio
_dirs:
	@mkdir -p $(WORK_DIRS)


# ──────────────────────────────────────────────────────────────────────
# TESTS
# ──────────────────────────────────────────────────────────────────────

## Corre los tests que NO requieren hardware (igual que el CI)
test:
	$(PYTEST) \
		test_sentinel.py tools/test_sentinel.py tools/test_rfscanner.py \
		-m "not hardware and not root" \
		-k "not RealHardware" \
		--tb=short -q

## Tests con reporte de cobertura completo
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

## SOLO los tests de hardware (requiere RTL-SDR conectado)
test-hardware:
	@echo "⚠ Requiere RTL-SDR conectado"
	$(PYTEST) \
		tools/test_rfscanner.py \
		-k "RealHardware" \
		-m "hardware" \
		--tb=short -v

## Todos los tests (incluye hardware — para uso local con SDR conectado)
test-all:
	$(PYTEST) \
		test_sentinel.py tools/test_sentinel.py tools/test_rfscanner.py \
		--tb=short -q


# ──────────────────────────────────────────────────────────────────────
# CALIDAD DE CÓDIGO
# ──────────────────────────────────────────────────────────────────────

## Ruff — lint (muestra errores sin corregir)
lint:
	$(RUFF) check . --output-format=concise

## Ruff — corrige errores automáticamente + formatea
format:
	$(RUFF) check . --fix
	$(RUFF) format .

## Pyright — type checking
typecheck:
	$(PYRIGHT) --warnings

## Corre lint + typecheck + tests (idéntico al CI)
check: lint typecheck test
	@echo "✓ Todo en orden — el CI pasará"


# ──────────────────────────────────────────────────────────────────────
# EJECUCIÓN
# ──────────────────────────────────────────────────────────────────────

## Arranca Apex Sentinel
run:
	$(PYTHON) Main.py


# ──────────────────────────────────────────────────────────────────────
# LIMPIEZA
# ──────────────────────────────────────────────────────────────────────

## Elimina archivos __pycache__ y .pyc
clean-pyc:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

## Limpieza completa (incluye .venv, htmlcov, .coverage)
clean: clean-pyc
	rm -rf .venv htmlcov .coverage coverage.xml dist build *.egg-info
	@echo "✓ Limpieza completa"


# ──────────────────────────────────────────────────────────────────────
# AYUDA
# ──────────────────────────────────────────────────────────────────────

## Muestra esta ayuda
help:
	@echo ""
	@echo "  APEX SENTINEL — Makefile"
	@echo ""
	@grep -E '^## .+' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = "## "}; {printf "  \033[36m%-20s\033[0m %s\n", prev, $$2} {prev=$$1}' | \
		sed 's/^  Makefile://; s/^  //'
	@echo ""

.DEFAULT_GOAL := help
