if [ "${kitflow_checked_lint:-0}" != 1 ]; then
    mise run --quiet lint
    kitflow_checked_lint=1
fi
