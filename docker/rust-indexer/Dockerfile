FROM rust:latest
WORKDIR /indexer
COPY tools/rust-syn-indexer/ .
RUN cargo build --release
ENTRYPOINT ["/indexer/target/release/rust-syn-indexer"]
