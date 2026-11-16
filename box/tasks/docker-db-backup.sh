if [ -n "${usage_file:-}" ]; then
    mise run --quiet db:backup --docker "$usage_file"
else
    mise run --quiet db:backup --docker
fi
