// Prisma ORM 7. Run through mise so the project's .env is loaded.
import { defineConfig } from "prisma/config";

export default defineConfig({
  schema: process.env.PRISMA_SCHEMA_PATH ?? "prisma/schema.prisma",
  migrations: {
    path: process.env.PRISMA_MIGRATIONS_PATH ?? "prisma/migrations",
  },
  datasource: {
    url: process.env.DATABASE_URL ?? "",
  },
});
