#!/bin/zsh

# One-click setup for the ticky source checkout.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
ROOT="${0:A:h}"

printf '\nStarting ticky setup...\n\n'
if "$ROOT/ticky" init --yes; then
  printf '\nTicky is ready. Restart connected Codex or Claude sessions to refresh their agent tools.\n\n'
  "$ROOT/ticky" status
  result=0
else
  result=$?
  printf '\nTicky setup failed with exit code %s. Review the error above.\n' "$result"
fi

printf '\nPress Return to close this window.'
read -r
exit "$result"
