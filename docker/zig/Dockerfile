FROM debian:bookworm-slim

ARG ZIG_VERSION=0.16.0
ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl xz-utils \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    case "$TARGETARCH" in \
      amd64) ZIG_ARCH="x86_64-linux" ;; \
      arm64) ZIG_ARCH="aarch64-linux" ;; \
      *) echo "unsupported arch: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://ziglang.org/download/${ZIG_VERSION}/zig-${ZIG_ARCH}-${ZIG_VERSION}.tar.xz" -o /tmp/zig.tar.xz; \
    mkdir -p /opt/zig; \
    tar -xJf /tmp/zig.tar.xz -C /opt/zig --strip-components=1; \
    rm /tmp/zig.tar.xz; \
    ln -s /opt/zig/zig /usr/local/bin/zig

WORKDIR /work

CMD ["zig", "version"]
