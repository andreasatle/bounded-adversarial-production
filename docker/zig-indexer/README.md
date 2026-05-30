# baps-zig-indexer Docker image

Runs the `zig-indexer` binary, which parses Zig source via `std.zig.Ast`
and emits a JSON index of top-level items to stdout.

## Build

```
docker build -t baps-zig-indexer:latest -f docker/zig-indexer/Dockerfile .
```

## Usage

`ZigLanguagePlugin` invokes it automatically:

```
docker run --rm -i baps-zig-indexer:latest < source.zig
```

Reads Zig source from stdin, writes JSON to stdout. No arguments required.
