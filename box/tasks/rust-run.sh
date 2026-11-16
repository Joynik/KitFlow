if [ -n "${RUST_BINARY:-}" ]; then
    cargo run --quiet --bin "$RUST_BINARY"
else
    cargo run --quiet
fi
