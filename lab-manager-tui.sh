#!/usr/bin/env bash
# lab-manager-tui.sh — Launch the OVE Lab Manager TUI
#
# Usage:
#   ./lab-manager-tui.sh
#
# Requires: textual (pip install textual)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv if present
if [[ -f .venv/bin/activate ]]; then
    source .venv/bin/activate
fi

exec python -m ove_tui "$@"
