FROM baps-zig:latest
WORKDIR /indexer
COPY tools/zig-indexer/ .
RUN zig build -Doptimize=ReleaseSafe
ENTRYPOINT ["/indexer/zig-out/bin/zig-indexer"]
