# Tiny, dependency-free facts-acquisition worker (stdlib only).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1
WORKDIR /app
COPY acquire_loop.py /app/acquire_loop.py

# Non-root for NAS hygiene.
RUN useradd -m runner
USER runner

ENTRYPOINT ["python", "/app/acquire_loop.py"]
