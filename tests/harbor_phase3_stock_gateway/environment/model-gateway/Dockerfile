FROM python:3.12-slim-bookworm

WORKDIR /opt/autobench
COPY benchmark_core/ /opt/autobench/benchmark_core/
COPY server.py /opt/autobench/server.py
ENV PYTHONPATH=/opt/autobench
CMD ["python", "/opt/autobench/server.py"]
