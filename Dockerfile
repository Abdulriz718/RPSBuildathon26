# Built on linux/amd64 by the scorer. Runs with no network, read-only root (writable /tmp),
# 1 CPU, 512 MB, uid 65534, map at /arena.
FROM python:3.13.9-slim-bookworm@sha256:b685a4fa58bb19d1814d78a1ec0f0208f351452724f78b20212c984d6e124a34
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir numpy==2.3.4
WORKDIR /bot
COPY bot/ /bot/
RUN python -m compileall -q /bot
ENTRYPOINT ["python3", "-u", "/bot/main.py"]
