#!/bin/bash
set -uo pipefail

mkdir -p /logs/verifier
reward=0
if [ "$(cat /testbed/AUTOBENCH_TRANSPORT_PROBE.txt 2>/dev/null || true)" = "harbor official regrade transport probe" ] \
   && ! git -C /testbed ls-files --error-unmatch AUTOBENCH_TRANSPORT_PROBE.txt >/dev/null 2>&1; then
    reward=1
fi
printf '%s\n' "$reward" > /logs/verifier/reward.txt
if [ "$reward" -ne 1 ]; then
    echo "Harbor transport marker was not preserved as an uncommitted repository change" >&2
    exit 1
fi
