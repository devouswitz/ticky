#!/bin/zsh

# One-click setup for the ticky source checkout.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
ROOT="${0:A:h}"

if ! command -v python3 >/dev/null 2>&1; then
  printf '\nTicky requires Python 3.11 or newer, but python3 was not found.\n'
  result=1
elif ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
  printf '\nTicky requires Python 3.11 or newer. The current python3 is too old.\n'
  result=1
else
  printf '\nStarting ticky setup...\n\n'
  if "$ROOT/ticky" init; then
    printf '\nChecking ticky status...\n\n'
    if "$ROOT/ticky" status; then
      printf '\nTicky is ready. Restart connected Codex or Claude sessions to refresh their agent tools.\n'
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
