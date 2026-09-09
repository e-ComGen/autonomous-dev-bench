FROM ubuntu:24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends git python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /workspace /opt/autobench \
    && git -C /workspace init -b benchmark \
    && git -C /workspace config user.name "Benchmark fixture" \
    && git -C /workspace config user.email "fixture@example.invalid" \
    && printf 'baseline\n' > /workspace/message.txt \
    && git -C /workspace add message.txt \
    && git -C /workspace commit -m "Baseline"

COPY run_adcp_fake.py /opt/autobench/run_adcp.py
RUN chmod 0555 /opt/autobench/run_adcp.py

WORKDIR /workspace
