run_compose() {
    if [ -n "${COMPOSE_WRAPPER:-}" ]; then
        case "$COMPOSE_WRAPPER" in
            /*) wrapper=$COMPOSE_WRAPPER ;;
            *) wrapper="${MISE_CONFIG_ROOT:-$PWD}/$COMPOSE_WRAPPER" ;;
        esac
        sh "$wrapper" "$@"
    else
        docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" "$@"
    fi
}
