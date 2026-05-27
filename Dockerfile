ARG BLENDER_VERSION=4.2.0
FROM debian:12-slim

ARG BLENDER_VERSION
ENV DEBIAN_FRONTEND=noninteractive
ENV BLENDER_VERSION=${BLENDER_VERSION}
ENV BLENDER_HOME=/opt/blender
ENV PATH=/opt/blender:${PATH}

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    libegl1 \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libx11-6 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxkbcommon0 \
    libxrender1 \
    libxxf86vm1 \
    python3 \
    python3-opencv \
    python3-pil \
    python3-pip \
    unzip \
    xz-utils \
  && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    major_minor="$(printf '%s' "${BLENDER_VERSION}" | awk -F. '{print $1 "." $2}')"; \
    curl -fL "https://download.blender.org/release/Blender${major_minor}/blender-${BLENDER_VERSION}-linux-x64.tar.xz" -o /tmp/blender.tar.xz; \
    mkdir -p /opt; \
    tar -xJf /tmp/blender.tar.xz -C /opt; \
    mv "/opt/blender-${BLENDER_VERSION}-linux-x64" "${BLENDER_HOME}"; \
    rm /tmp/blender.tar.xz; \
    blender --background --version

WORKDIR /workspace
CMD ["blender", "--background", "--python", "scripts/blender_smoke.py"]
