FROM ubuntu:24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends git python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /workspace/zone_a /workspace/zone_b /opt/autobench /opt/adcp \
    && git -C /workspace init -b benchmark \
    && git -C /workspace config user.name "Benchmark private qualification" \
    && git -C /workspace config user.email "phase3c@example.invalid" \
    && git -C /workspace config core.autocrlf false \
    && printf 'def price(quantity):\n    return quantity * 7\n' > /workspace/zone_a/pricing.py \
    && printf "OWNER = 'external-zone-B'\n" > /workspace/zone_b/owned.py \
    && git -C /workspace add zone_a/pricing.py zone_b/owned.py \
    && git -C /workspace commit -m "Phase 3C2 baseline"

# These three inputs are generated only inside the trusted private qualification
# job. They are never committed to or uploaded by the public benchmark repo.
COPY adcp-source/ /opt/adcp/
COPY adcp_source_identity.json /opt/autobench/adcp_source_identity.json
COPY run_adcp_private.py /opt/autobench/run_adcp.py
RUN chmod 0555 /opt/autobench/run_adcp.py

WORKDIR /workspace
