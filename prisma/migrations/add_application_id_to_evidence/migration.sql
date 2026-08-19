-- Add optional application_id column to StructuredEvidence
ALTER TABLE "StructuredEvidence" ADD COLUMN "application_id" VARCHAR(255);

-- Create index for fast application queries
CREATE INDEX "StructuredEvidence_application_id_idx" ON "StructuredEvidence"("application_id");
