manifest=Cargo.toml
if [ ! -f "$manifest" ]; then
    manifest=src-tauri/Cargo.toml
fi
cargo clippy --manifest-path "$manifest" --all-targets -- -D warnings
