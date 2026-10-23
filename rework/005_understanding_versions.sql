BEGIN;
ALTER TABLE logis_candidate.understanding_jobs ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 1 CHECK(version>0);
INSERT INTO logis_candidate.schema_migrations(version) VALUES(5) ON CONFLICT DO NOTHING;
COMMIT;
