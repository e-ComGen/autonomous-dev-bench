#!/bin/sh
set -eu

cd /workspace

test -f adcp-candidate.txt
grep -qx 'committed by phase3 ADCP transport stub' adcp-candidate.txt

test "$(git rev-list --count HEAD)" -eq 2
test "$(git log -1 --pretty=%s)" = 'Phase 3 committed candidate transport'
test -z "$(git status --porcelain=v1)"

mkdir -p /logs/verifier
printf '{"reward":1.0}\n' > /logs/verifier/reward.json
