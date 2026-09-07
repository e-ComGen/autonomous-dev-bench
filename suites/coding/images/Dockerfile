FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates bash && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --only-binary=:all: -r /tmp/requirements.txt && rm /tmp/requirements.txt
COPY native_driver.py /driver/native_driver.py
COPY provider /provider
WORKDIR /workspace
ENTRYPOINT ["python"]
