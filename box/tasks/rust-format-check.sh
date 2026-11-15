manifest=Cargo.toml
if [ ! -f "$manifest" ]; then
    manifest=src-tauri/Cargo.toml
fi
cargo fmt --manifest-path "$manifest" --all -- --check
