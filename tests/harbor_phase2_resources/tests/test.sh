#!/bin/bash
set -uo pipefail
mkdir -p /logs/verifier
reward=0
memory_max="$(cat /sys/fs/cgroup/memory.max 2>/dev/null || true)"
read -r cpu_quota cpu_period < /sys/fs/cgroup/cpu.max || true
if [ "$memory_max" = "268435456" ] \
   && [ "${cpu_quota:-max}" != "max" ] \
   && [ -n "${cpu_period:-}" ] \
   && [ "$cpu_quota" -le "$cpu_period" ]; then
    reward=1
fi
printf '%s\n' "$reward" > /logs/verifier/reward.txt
if [ "$reward" -ne 1 ]; then
    echo "Expected cgroup limits missing: memory.max=$memory_max cpu.max=${cpu_quota:-?} ${cpu_period:-?}" >&2
    exit 1
fi
