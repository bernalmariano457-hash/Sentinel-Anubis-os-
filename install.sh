#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════
#  APEX SENTINEL — install.sh
#  Setup en un solo comando. Detecta plataforma automáticamente.
#
#  Uso:
#    ./install.sh              # auto-detect (recomendado)
#    ./install.sh --uconsole   # ClockworkPi uConsole + RTL-SDR
#    ./install.sh --termux     # Android / Termux
#    ./install.sh --kali       # Kali / Debian / Ubuntu
#    ./install.sh --dev        # desarrollo local (incluye linters y tests)
#    ./install.sh --help       # muestra esta ayuda
# ══════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Colores ───────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${CYAN}[*]${NC} $*"; }
ok()      { echo -e "${GREEN}[✓]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*" >&2; }
header()  { echo -e "\n${BOLD}${CYAN}══ $* ══${NC}"; }

# ── Detección de plataforma ───────────────────────────────────────────
detect_platform() {
    if [[ -n "${TERMUX_VERSION:-}" ]] || [[ -d "/data/data/com.termux" ]]; then
        echo "termux"
    elif [[ "$(uname -m)" == "aarch64" ]] && grep -qi "clockworkpi\|uconsole" /proc/device-tree/model 2>/dev/null; then
        echo "uconsole"
    elif command -v apt-get &>/dev/null; then
        echo "kali"
    else
        echo "generic"
    fi
}

# ── Verificar Python ──────────────────────────────────────────────────
check_python() {
    local py="${1:-python3}"
    if ! command -v "$py" &>/dev/null; then
        error "Python no encontrado. Instala Python 3.13+."
        exit 1
    fi
    local version
    version=$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    local major minor
    major=$(echo "$version" | cut -d. -f1)
    minor=$(echo "$version" | cut -d. -f2)
    if [[ $major -lt 3 ]] || [[ $major -eq 3 && $minor -lt 13 ]]; then
        error "Se requiere Python 3.13+. Versión detectada: $version"
        exit 1
    fi
    ok "Python $version detectado"
    echo "$py"
}

# ── Crear entorno virtual ─────────────────────────────────────────────
setup_venv() {
    local py="$1"
    if [[ -d ".venv" ]]; then
        warn ".venv ya existe — usando el existente"
    else
        info "Creando entorno virtual en .venv ..."
        "$py" -m venv .venv
        ok "Entorno virtual creado"
    fi
    # shellcheck source=/dev/null
    source .venv/bin/activate
    pip install --upgrade pip --quiet
}

# ── Instalar dependencias del sistema ─────────────────────────────────
install_system_deps() {
    local platform="$1"
    case "$platform" in
        uconsole|kali)
            if command -v apt-get &>/dev/null; then
                info "Instalando dependencias del sistema (apt) ..."
                sudo apt-get install -y --no-install-recommends \
                    rtl-sdr librtlsdr-dev \
                    libpcap-dev \
                    portaudio19-dev \
                    libffi-dev \
                    2>/dev/null || warn "Algunas dependencias del sistema no se pudieron instalar"
                ok "Dependencias del sistema instaladas"
            fi
            ;;
        termux)
            info "Instalando dependencias Termux ..."
            pkg install -y rtl-sdr python 2>/dev/null || warn "Algunas dependencias Termux no se pudieron instalar"
            ok "Dependencias Termux instaladas"
            ;;
    esac
}

# ── Instalar el paquete ────────────────────────────────────────────────
install_package() {
    local extras="$1"
    local platform="$2"
    local pip_args=()

    if [[ "$platform" == "termux" ]]; then
        pip_args+=("--break-system-packages")
    fi

    info "Instalando sentinel-anubis-os[$extras] ..."
    pip install -e ".[$extras]" "${pip_args[@]}" --quiet
    ok "Paquete instalado"
}

# ── Crear directorios de trabajo ──────────────────────────────────────
setup_dirs() {
    local dirs=(
        "data/logs"
        "data/evidence"
        "data/evidence/rf"
        "data/evidence/rf/iq"
        "data/evidence/mobile"
        "core/data/logs"
        "core/data/security"
        "plugins"
        "tests"
    )
    for d in "${dirs[@]}"; do
        mkdir -p "$d"
    done
    ok "Directorios de trabajo creados"
}

# ── Verificación final ────────────────────────────────────────────────
verify_install() {
    if python -c "import rich, bcrypt, cryptography" 2>/dev/null; then
        ok "Dependencias core verificadas"
    else
        error "Verificación fallida — revisa los errores anteriores"
        exit 1
    fi
}

# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════

main() {
    local mode="${1:-auto}"
    local platform
    platform=$(detect_platform)

    header "APEX SENTINEL — Instalación"
    info "Plataforma detectada: ${BOLD}$platform${NC}"

    # Resolver modo
    case "$mode" in
        --help|-h)
            grep "^#  " "$0" | sed 's/^#  //'
            exit 0
            ;;
        --uconsole)  platform="uconsole" ;;
        --termux)    platform="termux" ;;
        --kali)      platform="kali" ;;
        --dev)       platform="${platform}-dev" ;;
        auto) ;;  # usar la detección automática
        *)
            error "Modo desconocido: $mode"
            exit 1
            ;;
    esac

    # Elegir extras según plataforma
    local extras
    case "$platform" in
        uconsole)      extras="uconsole" ;;
        termux)        extras="termux" ;;
        *-dev)         extras="all" ;;
        *)             extras="network,rtlsdr" ;;
    esac

    # Python
    local py
    py=$(check_python "python3")

    # Termux no usa venv (interferencia con pkg)
    if [[ "$platform" != "termux" ]]; then
        setup_venv "$py"
    fi

    install_system_deps "${platform%%-dev}"
    install_package "$extras" "$platform"
    setup_dirs
    verify_install

    header "Instalación completa"
    echo ""
    if [[ "$platform" == "termux" ]]; then
        echo -e "  ${GREEN}python Main.py${NC}"
    else
        echo -e "  ${GREEN}source .venv/bin/activate${NC}"
        echo -e "  ${GREEN}python Main.py${NC}"
        if [[ "$extras" == "all" ]]; then
            echo -e "  ${GREEN}pytest${NC}                    # correr tests"
            echo -e "  ${GREEN}ruff check .${NC}              # linter"
            echo -e "  ${GREEN}pyright${NC}                   # type checker"
        fi
    fi
    echo ""
}

main "${1:-auto}"
