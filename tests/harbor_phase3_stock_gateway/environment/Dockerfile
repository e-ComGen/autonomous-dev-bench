FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/autobench/wheels /workspace \
    && git -C /workspace init -b benchmark \
    && git -C /workspace config user.name "Benchmark fixture" \
    && git -C /workspace config user.email "fixture@example.invalid" \
    && printf 'stock shared gateway baseline\n' > /workspace/README.txt \
    && git -C /workspace add README.txt \
    && git -C /workspace commit -m "Baseline"

COPY wheels/ /opt/autobench/wheels/
RUN python -m pip install --no-cache-dir --no-index --find-links=/opt/autobench/wheels deepseek-harness-sdk==0.1.2rc1

COPY runner.py /opt/autobench/run_stock_deepseek.py
WORKDIR /workspace
