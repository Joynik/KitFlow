docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" logs --tail 100 --follow
