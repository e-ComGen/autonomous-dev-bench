#!/bin/bash
set -uo pipefail

reward=0
if [ "$(cat /workspace/message.txt 2>/dev/null || true)" = "adcp candidate ready after repair" ]; then
    if ! git -C /workspace diff --quiet --exit-code -- message.txt; then
        reward=1
    fi
fi

mkdir -p /logs/verifier
printf '%s\n' "$reward" > /logs/verifier/reward.txt

if [ "$reward" -ne 1 ]; then
    echo "ADCP fake runner did not preserve the expected uncommitted candidate patch" >&2
    exit 1
fi
