if [ -n "${RUST_BINARY:-}" ]; then
    cargo run --quiet --release --bin "$RUST_BINARY"
else
    cargo run --quiet --release
fi
