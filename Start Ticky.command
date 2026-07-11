#!/bin/zsh

# One-click entry point for the ticky source checkout: runs first-time setup
# when needed, checks provider accounts, then opens the interactive session.
export PATH="$HOME/.local/bin:$HOME/.grok/bin:$HOME/.volta/bin:$HOME/.npm-global/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
setopt NUMERIC_GLOB_SORT
for node_bin in "$HOME"/.nvm/versions/node/*/bin(N); do
  export PATH="$node_bin:$PATH"
done
ROOT="${0:A:h}"
CONFIG="${TICKY_HOME:-$HOME/.ticky}/config.json"

if ! command -v python3 >/dev/null 2>&1; then
  printf '\nTicky requires Python 3.11 or newer, but python3 was not found.\n'
  result=1
elif ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
  printf '\nTicky requires Python 3.11 or newer. The current python3 is too old.\n'
  result=1
else
  result=0
  if [ ! -f "$CONFIG" ]; then
    printf '\nStarting ticky setup...\n\n'
    "$ROOT/ticky" setup --no-install --no-link
    result=$?
    if [ "$result" -ne 0 ]; then
      printf '\nTicky setup failed with exit code %s. Review the error above.\n' "$result"
    fi
  fi
  if [ "$result" -eq 0 ]; then
    printf '\nChecking ticky status...\n\n'
    if "$ROOT/ticky" status && "$ROOT/ticky" account status; then
      printf '\nTicky is ready. To connect a harness, run one of:\n'
      printf '  "%s/ticky" install codex\n' "$ROOT"
      printf '  "%s/ticky" install claude\n' "$ROOT"
      if [ -t 0 ]; then
        printf '\nDropping into the ticky session...\n\n'
        exec "$ROOT/ticky" ui
      fi
    else
      result=$?
      printf '\nTicky status check failed with exit code %s. Review the account details above.\n' "$result"
    fi
  fi
fi

printf '\nPress Return to close this window.'
read -r
exit "$result"
