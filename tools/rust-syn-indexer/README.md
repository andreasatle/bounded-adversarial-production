# rust-syn-indexer

Reads Rust source from stdin, parses it with `syn`, and emits a JSON index to stdout.

## Build

```
cargo build --release
# binary at tools/rust-syn-indexer/target/release/rust-syn-indexer
```

## Usage

```
cat src/lib.rs | ./target/release/rust-syn-indexer
```
