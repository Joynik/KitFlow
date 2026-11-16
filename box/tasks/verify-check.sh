if [ "${kitflow_verified_check:-0}" != 1 ]; then
    mise run --quiet check
    kitflow_verified_check=1
fi
