-- CreateTable ApplicationHistory
CREATE TABLE "ApplicationHistory" (
    "id" TEXT NOT NULL,
    "applicationId" TEXT NOT NULL,
    "stage" TEXT NOT NULL,
    "transitionAt" TIMESTAMP(3) NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ApplicationHistory_pkey" PRIMARY KEY ("id")
);

-- CreateTable ApplicationFollowup
CREATE TABLE "ApplicationFollowup" (
    "id" TEXT NOT NULL,
    "applicationId" TEXT NOT NULL,
    "actionType" TEXT NOT NULL,
    "dueDate" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "completedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "ApplicationFollowup_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "ApplicationHistory_applicationId_idx" ON "ApplicationHistory"("applicationId");

-- CreateIndex
CREATE INDEX "ApplicationHistory_transitionAt_idx" ON "ApplicationHistory"("transitionAt");

-- CreateIndex
CREATE INDEX "ApplicationFollowup_applicationId_idx" ON "ApplicationFollowup"("applicationId");

-- CreateIndex
CREATE INDEX "ApplicationFollowup_status_idx" ON "ApplicationFollowup"("status");

-- CreateIndex
CREATE INDEX "ApplicationFollowup_dueDate_idx" ON "ApplicationFollowup"("dueDate");

-- AddForeignKey
ALTER TABLE "ApplicationHistory" ADD CONSTRAINT "ApplicationHistory_applicationId_fkey" FOREIGN KEY ("applicationId") REFERENCES "Application"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ApplicationFollowup" ADD CONSTRAINT "ApplicationFollowup_applicationId_fkey" FOREIGN KEY ("applicationId") REFERENCES "Application"("id") ON DELETE CASCADE ON UPDATE CASCADE;
