if [ "${kitflow_checked_format_check:-0}" != 1 ]; then
    mise run --quiet format-check
    kitflow_checked_format_check=1
fi
