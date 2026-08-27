-- Store the complete MCP tracker/profile payloads in Postgres.
CREATE TABLE "CanonicalState" (
    "id" TEXT NOT NULL,
    "payload" JSONB NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "CanonicalState_pkey" PRIMARY KEY ("id")
);
