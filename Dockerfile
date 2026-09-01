# FretWise container image.
#
# Uses the official multi-arch pixi base image, so the same Dockerfile builds
# on linux/amd64 (linux-64) and linux/arm64 (linux-aarch64 — Jetson Orin, ARM
# Synology, ARM cloud). pixi resolves the correct locked environment per arch.
#
# Build:  docker build -t fretwise .
# Run:    docker run --rm -p 8080:8080 fretwise
#         -> open http://localhost:8080
# CLI:    docker run --rm -v "$PWD/partitions:/data" fretwise \
#             pixi run fretwise solve /data/song.gp5
#
ARG FRETWISE_MODELS_IMAGE=fretwise-models:local
FROM ${FRETWISE_MODELS_IMAGE} AS fingering-models

FROM ghcr.io/prefix-dev/pixi@sha256:10b20db5683f27fb40f5d915f460016189031d6c4e14b29255e66139e46d32d3 AS web-runtime

WORKDIR /app

# NAS/server contract: CPU inference only, no LLM wrapper or hardware MIDI output.
ENV FRETWISE_RUNTIME_PROFILE=server \
    FRETWISE_MODEL_DIR=/app/data/models \
    FRETWISE_REQUIRE_ML_MODELS=1 \
    FRETWISE_ONNX_THREADS=1

# Manifest + lock first for better layer caching.
COPY pixi.toml pixi.lock pyproject.toml README.md ./
# Source plus whitelisted runtime data. Local ignored ONNX files never enter
# this build context; production models come from an immutable private image.
COPY src ./src
COPY data ./data
COPY --from=fingering-models /models/*.onnx ./data/models/

# Install the server environment. It retains MIDI file parsing but excludes
# python-rtmidi, which is only present in the Pixi desktop/PC feature.
RUN COPYFILE_DISABLE=1 pixi install --locked -e server

# Image is launched with NAS UID/GID via Compose. Build layers are root-owned,
# so grant read/execute access without making application files writable.
RUN chmod -R a+rX /app

RUN install -d -o 1000 -g 10 -m 0750 /home/fretwise
ENV HOME=/home/fretwise
USER 1000:10

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD /app/.pixi/envs/server/bin/python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/ready', timeout=3)"

# Bind to 0.0.0.0 so the UI is reachable from outside the container.
CMD ["/app/.pixi/envs/server/bin/fretwise", "web", "--dir", "/data/partitions", "--host", "0.0.0.0", "--port", "8080"]
