#!/usr/bin/env bash
# ====================================================================
# Vieed Editor Installer & Environment Setup Script
# Author: vieexploit (https://github.com/vieexploit)
# ====================================================================
# Purpose : create a venv, install Vieed (editable, deps from
#           pyproject.toml), and do optional Ollama setup.
# Option  : ./install.sh --skip-ai   -> skip all AI setup.
# ====================================================================

set -euo pipefail

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
RESET="\033[0m"

info()  { echo -e "${GREEN}$1${RESET}"; }
warn()  { echo -e "${YELLOW}$1${RESET}"; }
error() { echo -e "${RED}$1${RESET}"; }

# Always run from the script's directory (not the user's CWD)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SKIP_AI=0
if [ "${1:-}" = "--skip-ai" ]; then
    SKIP_AI=1
fi

echo -e "${GREEN}${BOLD}=== Starting Vieed TUI Editor Setup ===${RESET}\n"

# 0. Terminal sanity check (a TUI needs an interactive terminal)
if [ -z "${TERM:-}" ] || [ "$TERM" = "dumb" ]; then
    warn "WARNING: TERM is not set correctly ('${TERM:-empty}')."
    warn "Vieed needs an interactive terminal (e.g. xterm-256color, tmux)."
fi

# 1. Check Python3
if ! command -v python3 &> /dev/null; then
    error "Error: Python3 not found. Please install Python3 first."
    exit 1
fi

# 2. venv (in the script's directory, idempotent)
echo -e "${YELLOW}[1/3] Setting up Python virtual environment (venv)...${RESET}"
if [ ! -d "$SCRIPT_DIR/venv" ]; then
    python3 -m venv venv
    info "Virtual environment 'venv' created."
else
    info "Virtual environment 'venv' already exists, skipping."
fi
# shellcheck disable=SC1091
source venv/bin/activate

# 3. Install Vieed as editable — pinned deps are read from pyproject.toml
echo -e "\n${YELLOW}[2/3] Installing Vieed (editable) with its dependencies...${RESET}"
pip install --upgrade pip setuptools wheel > /dev/null
pip install -e .
info "Vieed installed. The 'vieed' command is available in venv/bin/."

# 4. Ollama (OPTIONAL — the editor works fine without AI)
if [ "$SKIP_AI" -eq 1 ]; then
    warn "\n[3/3] --skip-ai: skipping Ollama setup. AI features disabled."
else
    echo -e "\n${YELLOW}[3/3] Checking Ollama installation...${RESET}"
    if ! command -v ollama &> /dev/null; then
        warn "Ollama not found on this system. AI features disabled."
        warn "To enable them:"
        warn "  1. Install : ${BOLD}curl -fsSL https://ollama.com/install.sh | sh${RESET}"
        warn "  2. Re-run  : ${BOLD}./install.sh${RESET}"
    else
        info "Ollama detected."

        # Start the daemon if not running, with a retry loop
        if ollama list &> /dev/null; then
            info "Ollama daemon is already running."
        else
            warn "Ollama daemon not running, starting it..."
            nohup ollama serve > /dev/null 2>&1 &
            disown || true
            READY=0
            for _ in $(seq 1 15); do
                if ollama list &> /dev/null; then
                    READY=1
                    break
                fi
                sleep 1
            done
            if [ "$READY" -ne 1 ]; then
                warn "Ollama daemon did not respond within 15 seconds."
                warn "Try running it manually: ${BOLD}ollama serve${RESET}, then re-run this script."
            fi
        fi

        # Pull the model only if not present yet
        if ollama list &> /dev/null; then
            if ollama list | awk 'NR>1 {print $1}' | grep -qx "qwen2.5-coder:1.5b"; then
                info "Model 'qwen2.5-coder:1.5b' is already available."
            else
                if ollama pull qwen2.5-coder:1.5b; then
                    info "Model 'qwen2.5-coder:1.5b' pulled successfully."
                else
                    warn "Failed to pull model (check connection/model name). AI features may fail."
                fi
            fi
        fi
    fi
fi

echo -e "\n${GREEN}${BOLD}====================================================${RESET}"
echo -e "${GREEN}${BOLD} Setup complete! Vieed is ready to use. ${RESET}"
echo -e "${GREEN}${BOLD}====================================================${RESET}"
echo -e "Run Vieed either way:"
echo -e "  ${BOLD}source venv/bin/activate && vieed [filename]${RESET}"
echo -e "  or directly: ${BOLD}$SCRIPT_DIR/venv/bin/vieed [filename]${RESET}\n"
