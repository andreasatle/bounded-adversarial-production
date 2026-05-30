# baps-rust-indexer Docker image

Runs the `rust-syn-indexer` binary, which parses Rust source via the `syn` crate
and emits a JSON index of top-level items to stdout.

## Build

```
docker build -t baps-rust-indexer:latest docker/rust-indexer/
```

## Usage

`RustLanguagePlugin` invokes it automatically:

```
docker run --rm -i baps-rust-indexer:latest < source.rs
```

Reads Rust source from stdin, writes JSON to stdout. No arguments required.
