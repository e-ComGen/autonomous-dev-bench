FROM ubuntu:24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /workspace \
    && git -C /workspace init -b benchmark \
    && git -C /workspace config user.name "Benchmark fixture" \
    && git -C /workspace config user.email "fixture@example.invalid" \
    && printf 'baseline\n' > /workspace/message.txt \
    && git -C /workspace add message.txt \
    && git -C /workspace commit -m "Baseline"

WORKDIR /workspace
