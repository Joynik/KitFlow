if [ "${kitflow_checked_app:-0}" != 1 ]; then
    mise run --quiet app-check
    kitflow_checked_app=1
fi
