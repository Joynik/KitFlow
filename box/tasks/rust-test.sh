manifest=Cargo.toml
if [ ! -f "$manifest" ]; then
    manifest=src-tauri/Cargo.toml
fi
cargo test --manifest-path "$manifest" --all-targets
