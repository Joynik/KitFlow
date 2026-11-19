if [ "${usage_docker:-false}" = true ]; then DATABASE_EXECUTION_MODE=docker; fi
case "${DATABASE_EXECUTION_MODE:-native}" in
    native) ;;
    docker)
        : "${COMPOSE_FILE:?Select Docker or set COMPOSE_FILE}"
        : "${COMPOSE_ENV_FILE:?Set COMPOSE_ENV_FILE}"
        : "${DATABASE_DOCKER_SERVICE:?Set vars.database_docker_service}"
        ;;
    *) echo "DATABASE_EXECUTION_MODE must be native or docker" >&2; exit 2 ;;
esac
input=${usage_file:-${DATABASE_RESTORE_FILE:-}}
[ -n "$input" ] && [ -f "$input" ] || { echo "Specify an existing SQL restore file" >&2; exit 2; }
if [ "${DATABASE_EXECUTION_MODE:-native}" = docker ]; then
    run_compose exec -T "$DATABASE_DOCKER_SERVICE" psql --quiet --no-psqlrc --set ON_ERROR_STOP=1 --single-transaction < "$input"
else
    psql --quiet --no-psqlrc --set ON_ERROR_STOP=1 --single-transaction --file "$input"
fi
