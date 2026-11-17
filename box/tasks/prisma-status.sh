NO_COLOR=1 PRISMA_HIDE_UPDATE_MESSAGE=1 bunx --bun --no-install prisma migrate status --config "${PRISMA_CONFIG:-prisma.config.ts}"
