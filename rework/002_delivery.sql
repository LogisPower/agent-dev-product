BEGIN;
ALTER TABLE logis_candidate.outbox ADD COLUMN IF NOT EXISTS lease_until timestamptz;
ALTER TABLE logis_candidate.outbox ADD COLUMN IF NOT EXISTS lease_token text;
ALTER TABLE logis_candidate.outbox ADD COLUMN IF NOT EXISTS dead_letter boolean NOT NULL DEFAULT false;
CREATE TABLE IF NOT EXISTS logis_candidate.consumer_receipts(consumer text NOT NULL,event_id text NOT NULL REFERENCES logis_candidate.events(event_id),completed_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(consumer,event_id));
CREATE TABLE IF NOT EXISTS logis_candidate.activity_projection(event_id text PRIMARY KEY REFERENCES logis_candidate.events(event_id),project_id text NOT NULL,object_id text NOT NULL,event_type text NOT NULL,record_version integer NOT NULL,created_at timestamptz NOT NULL DEFAULT now());
INSERT INTO logis_candidate.schema_migrations(version) VALUES(2) ON CONFLICT DO NOTHING;
COMMIT;
