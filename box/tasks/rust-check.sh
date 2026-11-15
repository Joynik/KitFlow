manifest=Cargo.toml
if [ ! -f "$manifest" ]; then
    manifest=src-tauri/Cargo.toml
fi
cargo check --manifest-path "$manifest" --all-targets
