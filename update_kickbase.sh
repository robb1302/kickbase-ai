#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

usage() {
    cat <<'EOF'
Usage: ./update_kickbase.sh

Runs the local Kickbase data update pipeline.
EOF
}

die() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

while (($#)); do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "Unknown option: $1 (use --help for usage)"
            ;;
    esac
    shift
done

if [[ -n "${PYTHON:-}" ]]; then
    BASE_PYTHON="$PYTHON"
elif command -v python3 >/dev/null 2>&1; then
    BASE_PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    BASE_PYTHON="$(command -v python)"
else
    die "Python was not found. Install Python 3.11 or set PYTHON to its executable."
fi

if [[ ! -f .venv/bin/python && ! -f .venv/Scripts/python.exe ]]; then
    printf '==> Creating local virtual environment\n'
    "$BASE_PYTHON" -m venv .venv
fi

if [[ -f .venv/bin/python ]]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif [[ -f .venv/Scripts/python.exe ]]; then
    PYTHON_BIN="$ROOT_DIR/.venv/Scripts/python.exe"
else
    die "Could not find the Python executable in .venv."
fi

run_step() {
    local label="$1"
    shift
    printf '\n==> %s\n' "$label"
    "$@"
}

run_step "Upgrade pip" "$PYTHON_BIN" -m pip install --upgrade pip
run_step "Install Python dependencies" "$PYTHON_BIN" -m pip install -r requirements.txt

case "$(uname -s)" in
    Linux*)
        run_step "Install Playwright Chromium and Linux dependencies" "$PYTHON_BIN" -m playwright install --with-deps chromium
        ;;
    *)
        run_step "Install Playwright Chromium" "$PYTHON_BIN" -m playwright install chromium
        ;;
esac

run_step "Download MAIK scores" "$PYTHON_BIN" src/maiks_score_downloader.py
run_step "Download LigaInsider player links" "$PYTHON_BIN" src/ligainsider_player_downloader.py
run_step "Download LigaInsider matchday lineups" "$PYTHON_BIN" src/ligainsider_matchday_downloader.py
run_step "Download Kickbase player data" "$PYTHON_BIN" src/kickbase_downloader.py
run_step "Merge player data" "$PYTHON_BIN" src/merger.py
run_step "Update starting lineup flags" "$PYTHON_BIN" src/set_starter.py

printf '\nUpdate finished. No Git commit or push was performed.\n'
