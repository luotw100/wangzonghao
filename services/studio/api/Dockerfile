FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir uv -i http://mirrors.aliyun.com/pypi/simple --trusted-host=mirrors.aliyun.com

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY studio ./studio
COPY admin ./admin

CMD ["uv", "run", "uvicorn", "studio.main:app", "--host", "0.0.0.0", "--port", "23456"]