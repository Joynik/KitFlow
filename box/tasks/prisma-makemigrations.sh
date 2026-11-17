NO_COLOR=1 PRISMA_HIDE_UPDATE_MESSAGE=1 bunx --bun --no-install prisma migrate dev --create-only --name "${usage_name:-update_schema}" --config "${PRISMA_CONFIG:-prisma.config.ts}"
