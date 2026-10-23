BEGIN;
ALTER TABLE logis_candidate.activity_projection ADD COLUMN IF NOT EXISTS sequence bigserial;
CREATE UNIQUE INDEX IF NOT EXISTS activity_sequence ON logis_candidate.activity_projection(sequence);
CREATE INDEX IF NOT EXISTS activity_project_sequence ON logis_candidate.activity_projection(project_id,sequence);
INSERT INTO logis_candidate.schema_migrations(version) VALUES(3) ON CONFLICT DO NOTHING;
COMMIT;
