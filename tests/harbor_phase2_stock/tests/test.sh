#!/bin/bash
set -uo pipefail

mkdir -p /logs/verifier
reward=0
content="$(cat /workspace/stock-harness.txt 2>/dev/null || true)"
if [ "$content" = "created by stock deepseek harness" ] \
   && ! git -C /workspace ls-files --error-unmatch stock-harness.txt >/dev/null 2>&1; then
    reward=1
fi
printf '%s\n' "$reward" > /logs/verifier/reward.txt
if [ "$reward" -ne 1 ]; then
    echo "Stock DeepSeek Harness did not create the expected uncommitted file" >&2
    exit 1
fi
