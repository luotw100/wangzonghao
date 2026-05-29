FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build context is the repo root so we can pull in both the sidecar
# package (desktop/sidecar) and the bridge_host service itself.

COPY desktop/sidecar /opt/sidecar
RUN pip install --no-cache-dir -i http://mirrors.aliyun.com/pypi/simple --trusted-host=mirrors.aliyun.com \
        fastapi==0.115.0 uvicorn==0.30.6 pydantic==2.9.2 \
    && pip install --no-cache-dir /opt/sidecar

COPY services/bridge_host/bridge_host ./bridge_host

EXPOSE 23458

CMD ["uvicorn", "bridge_host.app:app", "--host", "0.0.0.0", "--port", "23458"]
