if [ "${kitflow_verified_test:-0}" != 1 ]; then
    mise run --quiet test
    kitflow_verified_test=1
fi
