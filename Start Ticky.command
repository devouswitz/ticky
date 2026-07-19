#!/bin/zsh

# One-click entry point for the ticky source checkout. The Python `start`
# command owns setup and readiness policy so every entry point behaves alike.
export PATH="$HOME/.local/bin:$HOME/.grok/bin:$HOME/.volta/bin:$HOME/.npm-global/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
setopt NUMERIC_GLOB_SORT
for node_bin in "$HOME"/.nvm/versions/node/*/bin(N); do
  export PATH="$node_bin:$PATH"
done
ROOT="${0:A:h}"

if ! command -v python3 >/dev/null 2>&1; then
  printf '\nTicky requires Python 3.11 or newer, but python3 was not found.\n'
  result=1
elif ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
  printf '\nTicky requires Python 3.11 or newer. The current python3 is too old.\n'
  result=1
else
  if [ -t 0 ]; then
    exec "$ROOT/ticky" start
  fi
  "$ROOT/ticky" start
  result=$?
fi

if [ "$result" -ne 0 ]; then
  printf '\nTicky could not start. Review the message above.\n'
fi
printf '\nPress Return to close this window.'
read -r
exit "$result"
