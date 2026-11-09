#!/bin/sh
# Optional local scheduler entry. The private snapshot is never uploaded.
set -eu
cd "$(dirname "$0")/.."
umask 077
mkdir -p data/runs
stage="$(mktemp -d "$PWD/data/refresh.XXXXXX")"
day="$(date -u +%Y-%m-%dT%H%M%SZ)"
limit="${ATLAS_LIMIT:-250}"
if [ -n "${ATLAS_RANKING:-}" ]; then
  python3 -m equity_atlas --limit "$limit" --out "$stage" --ranking "$ATLAS_RANKING"
else
  python3 -m equity_atlas --limit "$limit" --out "$stage"
fi
mv "$stage" "data/runs/$day"
printf '%s\n' "data/runs/$day" > data/latest.tmp
mv data/latest.tmp data/latest
