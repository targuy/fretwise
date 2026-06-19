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
FROM ghcr.io/prefix-dev/pixi:latest AS base

WORKDIR /app

# Manifest + lock first for better layer caching.
COPY pixi.toml pixi.lock pyproject.toml README.md ./
# Source and runtime data (patterns, profiles, ONNX models) needed by the editable install.
COPY src ./src
COPY data ./data

# Install the locked default environment for this image's architecture.
RUN COPYFILE_DISABLE=1 pixi install --locked -e default

EXPOSE 8080

# Bind to 0.0.0.0 so the UI is reachable from outside the container.
CMD ["pixi", "run", "fretwise", "web", "--host", "0.0.0.0", "--port", "8080"]
