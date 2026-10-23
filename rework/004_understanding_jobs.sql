BEGIN;
CREATE TABLE IF NOT EXISTS logis_candidate.understanding_jobs(
 id text PRIMARY KEY REFERENCES logis_candidate.messages(id),
 project_id text NOT NULL REFERENCES logis_candidate.projects(id),
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','completed','failed')),
 attempts integer NOT NULL DEFAULT 0,
 available_at timestamptz NOT NULL DEFAULT now(),
 lease_until timestamptz, lease_token text,
 result jsonb, last_error text,
 created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz
);
CREATE INDEX IF NOT EXISTS understanding_pending ON logis_candidate.understanding_jobs(status,available_at);
INSERT INTO logis_candidate.schema_migrations(version) VALUES(4) ON CONFLICT DO NOTHING;
COMMIT;
