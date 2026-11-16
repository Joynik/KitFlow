if [ -n "${usage_file:-}" ]; then
    mise run --quiet db:restore --docker "$usage_file"
else
    mise run --quiet db:restore --docker
fi
