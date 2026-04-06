#!/usr/bin/env bash
# Shared check: ensure Python and klore are available.
# Source this from command scripts: source "$(dirname "$0")/_check-klore.sh"

if ! command -v python3 &>/dev/null; then
  echo "Error: Python 3 is required but not found." >&2
  echo "Install Python 3.10+ from https://python.org" >&2
  exit 1
fi

# Check if klore is available on PATH
if command -v klore &>/dev/null; then
  : # found
elif [ -x "$HOME/.klore-venv/bin/klore" ]; then
  # Found in standard klore venv
  export PATH="$HOME/.klore-venv/bin:$PATH"
elif python3 -c "import klore" &>/dev/null; then
  klore() { python3 -m klore "$@"; }
else
  # Auto-install into a dedicated venv
  echo "klore not found. Installing..." >&2
  python3 -m venv "$HOME/.klore-venv" 2>/dev/null
  if [ $? -eq 0 ]; then
    "$HOME/.klore-venv/bin/pip" install --quiet klore 2>/dev/null
    if [ $? -eq 0 ]; then
      export PATH="$HOME/.klore-venv/bin:$PATH"
      echo "Installed klore to ~/.klore-venv" >&2
    else
      echo "Failed to install klore from PyPI. Install manually:" >&2
      echo "  pip install klore" >&2
      exit 1
    fi
  else
    echo "Could not create venv. Install klore manually:" >&2
    echo "  pipx install klore" >&2
    echo "  pip install klore" >&2
    exit 1
  fi
fi
