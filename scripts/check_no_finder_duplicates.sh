#!/usr/bin/env bash
# Reject Finder-style duplicate filenames ("foo 2.py") in the repo tree.
# Finding #22 — run locally or in CI.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

# Tracked paths only (ignore untracked / venv)
bad="$(git ls-files -z | tr '\0' '\n' | grep -E ' 2(\.|$)' || true)"
if [[ -n "$bad" ]]; then
  echo "Finder-style duplicate filenames are not allowed:" >&2
  echo "$bad" >&2
  exit 1
fi
echo "OK: no tracked '* 2.*' Finder duplicates"
