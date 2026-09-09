#!/bin/bash
set -uo pipefail

reward=0
if [ "$(cat /workspace/message.txt 2>/dev/null || true)" = "harbor substrate qualified" ]; then
    if ! git -C /workspace diff --quiet --exit-code -- message.txt; then
        reward=1
    fi
fi

mkdir -p /logs/verifier
printf '%s\n' "$reward" > /logs/verifier/reward.txt

if [ "$reward" -ne 1 ]; then
    echo "Harbor workspace mutation or uncommitted patch was not preserved" >&2
    exit 1
fi
