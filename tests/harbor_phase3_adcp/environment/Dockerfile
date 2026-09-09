FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/autobench /workspace \
    && git -C /workspace init -b benchmark \
    && git -C /workspace config user.name "Benchmark fixture" \
    && git -C /workspace config user.email "fixture@example.invalid" \
    && printf 'phase3 adcp baseline\n' > /workspace/README.txt \
    && git -C /workspace add README.txt \
    && git -C /workspace commit -m "Baseline"

COPY runner.py /opt/autobench/run_adcp.py
WORKDIR /workspace
