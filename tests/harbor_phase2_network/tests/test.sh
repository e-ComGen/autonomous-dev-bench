#!/bin/bash
set -uo pipefail
mkdir -p /logs/verifier
reward=0
if [ "$(cat /workspace/network-blocked.txt 2>/dev/null || true)" = "blocked" ]; then
    reward=1
fi
printf '%s\n' "$reward" > /logs/verifier/reward.txt
if [ "$reward" -ne 1 ]; then
    echo "Agent-side public egress was not proven blocked" >&2
    exit 1
fi
