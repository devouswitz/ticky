#!/bin/zsh

# One-click entry point for the ticky source checkout: runs first-time setup
# when needed, then drops into the interactive session.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
ROOT="${0:A:h}"
CONFIG="${TICKY_HOME:-$HOME/.ticky}/config.json"

if ! command -v python3 >/dev/null 2>&1; then
  printf '\nTicky requires Python 3.11 or newer, but python3 was not found.\n'
  result=1
elif ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
  printf '\nTicky requires Python 3.11 or newer. The current python3 is too old.\n'
  result=1
else
  if [ -t 0 ] && [ -f "$CONFIG" ]; then
    exec "$ROOT/ticky" ui
  fi
  printf '\nStarting ticky setup...\n\n'
  if "$ROOT/ticky" setup; then
    printf '\nChecking ticky status...\n\n'
    if "$ROOT/ticky" status && "$ROOT/ticky" account status; then
      printf '\nTicky is ready. Restart connected Codex or Claude sessions to refresh their agent tools.\n'
      if [ -t 0 ]; then
        printf '\nDropping into the ticky session...\n\n'
        exec "$ROOT/ticky" ui
      fi
      result=0
    else
      result=$?
      printf '\nTicky setup completed, but the status check failed with exit code %s.\n' "$result"
    fi
  else
    result=$?
    printf '\nTicky setup failed with exit code %s. Review the error above.\n' "$result"
  fi
fi

printf '\nPress Return to close this window.'
read -r
exit "$result"
