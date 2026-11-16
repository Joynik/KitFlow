if [ "${kitflow_checked_typecheck:-0}" != 1 ]; then
    mise run --quiet typecheck
    kitflow_checked_typecheck=1
fi
