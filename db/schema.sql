-- Life Admin OS — PostgreSQL schema v1.0
-- Implements the data model in Section 14 of the blueprint, plus provenance (S15),
-- property/family knowledge model (S16) and audit/security (S17).
-- Run: psql "$DATABASE_URL" -f db/schema.sql

CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pg_trgm";    -- fuzzy search
CREATE EXTENSION IF NOT EXISTS "citext";     -- case-insensitive email
CREATE EXTENSION IF NOT EXISTS "vector";     -- pgvector, for assistant retrieval

-- ---------------------------------------------------------------- enums
CREATE TYPE access_level     AS ENUM ('owner','admin','contributor','viewer');
CREATE TYPE doc_status       AS ENUM ('uploaded','scanning','processing','needs_review','verified','failed','archived');
CREATE TYPE field_source     AS ENUM ('ai_extracted','user_entered','imported','system_derived');
CREATE TYPE verify_status    AS ENUM ('unverified','verified','disputed','rejected');
CREATE TYPE asset_type       AS ENUM ('bank_account','investment','insurance','vehicle','jewellery','business','loan','subscription','other');
CREATE TYPE property_type    AS ENUM ('agricultural_land','residential_plot','house','apartment','commercial','ancestral_land','other');
CREATE TYPE deadline_status  AS ENUM ('open','snoozed','done','dismissed','expired');
CREATE TYPE priority_level   AS ENUM ('low','medium','high','critical');

-- ---------------------------------------------------------------- identity
CREATE TABLE users (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email           CITEXT UNIQUE NOT NULL,
  full_name       TEXT NOT NULL,
  password_hash   TEXT,                      -- NULL when using a managed auth provider
  auth_provider   TEXT NOT NULL DEFAULT 'local',
  external_id     TEXT,
  phone           TEXT,
  locale          TEXT NOT NULL DEFAULT 'en-IN',
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE families (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name            TEXT NOT NULL,
  owner_user_id   UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  settings        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A family member may or may not have a login (elders often will not).
CREATE TABLE family_members (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
  display_name    TEXT NOT NULL,
  relationship    TEXT,                      -- 'father','grandmother','self', free text
  date_of_birth   DATE,
  date_of_death   DATE,
  is_deceased     BOOLEAN NOT NULL DEFAULT FALSE,
  access          access_level NOT NULL DEFAULT 'viewer',
  invited_email   CITEXT,
  invite_token    TEXT,
  invite_expires  TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (family_id, user_id)
);
CREATE INDEX ON family_members (family_id);

-- Parent/child/spouse edges — the family graph (S16).
CREATE TABLE family_relationships (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  from_member_id  UUID NOT NULL REFERENCES family_members(id) ON DELETE CASCADE,
  to_member_id    UUID NOT NULL REFERENCES family_members(id) ON DELETE CASCADE,
  relation_type   TEXT NOT NULL,             -- 'parent_of','spouse_of','sibling_of'
  CHECK (from_member_id <> to_member_id),
  UNIQUE (from_member_id, to_member_id, relation_type)
);

-- ---------------------------------------------------------------- documents
CREATE TABLE documents (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  uploaded_by     UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  title           TEXT NOT NULL,
  category        TEXT,                      -- ai-assigned: insurance|property|vehicle|financial|government|other
  category_conf   NUMERIC(4,3),
  mime_type       TEXT NOT NULL,
  size_bytes      BIGINT NOT NULL,
  sha256          TEXT NOT NULL,
  storage_key     TEXT NOT NULL,             -- private object-storage key, never a public URL
  page_count      INT,
  status          doc_status NOT NULL DEFAULT 'uploaded',
  ocr_text        TEXT,
  error_message   TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON documents (family_id, status);
CREATE INDEX documents_text_trgm ON documents USING gin (ocr_text gin_trgm_ops);

CREATE TABLE document_versions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  version_no      INT NOT NULL,
  storage_key     TEXT NOT NULL,
  sha256          TEXT NOT NULL,
  created_by      UUID REFERENCES users(id),
  note            TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (document_id, version_no)
);

-- Chunked text + embeddings for grounded assistant retrieval (FR-015).
CREATE TABLE document_chunks (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  page_no         INT,
  chunk_index     INT NOT NULL,
  content         TEXT NOT NULL,
  embedding       vector(1024)
);
CREATE INDEX ON document_chunks (family_id);
CREATE INDEX document_chunks_vec ON document_chunks
  USING hnsw (embedding vector_cosine_ops);

-- ------------------------------------------------- provenance (Section 15)
-- Every extracted or entered fact carries where it came from and whether a
-- human has confirmed it. Nothing in the product is "true" until verified.
CREATE TABLE extracted_fields (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  document_id     UUID REFERENCES documents(id) ON DELETE CASCADE,
  subject_type    TEXT NOT NULL,             -- 'document','asset','property','deadline'
  subject_id      UUID,
  field_key       TEXT NOT NULL,             -- 'policy_number','expiry_date','area_acres'
  field_value     TEXT,
  value_json      JSONB,
  data_type       TEXT NOT NULL DEFAULT 'string',
  confidence      NUMERIC(4,3),
  source          field_source NOT NULL DEFAULT 'ai_extracted',
  source_page     INT,
  source_snippet  TEXT,
  source_bbox     JSONB,                     -- {x,y,w,h} for highlight-in-page
  verification    verify_status NOT NULL DEFAULT 'unverified',
  verified_by     UUID REFERENCES users(id),
  verified_at     TIMESTAMPTZ,
  model_name      TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON extracted_fields (subject_type, subject_id);
CREATE INDEX ON extracted_fields (document_id);

-- ---------------------------------------------------------------- registry
CREATE TABLE assets (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  type            asset_type NOT NULL,
  name            TEXT NOT NULL,
  institution     TEXT,
  identifier_last4 TEXT,                     -- never store full account numbers in clear
  value_estimate  NUMERIC(18,2),
  value_currency  TEXT DEFAULT 'INR',
  value_as_of     DATE,
  verification    verify_status NOT NULL DEFAULT 'unverified',
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON assets (family_id, type);

CREATE TABLE properties (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  label           TEXT NOT NULL,             -- 'Ancestral land, Barhi village'
  type            property_type NOT NULL,
  address_line    TEXT,
  village_locality TEXT,
  district        TEXT,
  state           TEXT,
  country         TEXT DEFAULT 'IN',
  pincode         TEXT,
  latitude        NUMERIC(9,6),
  longitude       NUMERIC(9,6),
  survey_number   TEXT,
  plot_number     TEXT,
  khata_number    TEXT,
  area_value      NUMERIC(14,4),
  area_unit       TEXT,                      -- 'acre','sqft','katha','bigha'
  recorded_holder TEXT,                      -- name as it appears on the record
  acquired_on     DATE,
  value_estimate  NUMERIC(18,2),
  value_as_of     DATE,
  verification    verify_status NOT NULL DEFAULT 'unverified',
  history_note    TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON properties (family_id);

-- Association, deliberately NOT legal title (Section 35).
CREATE TABLE ownership_records (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  member_id       UUID REFERENCES family_members(id) ON DELETE SET NULL,
  external_holder TEXT,                      -- non-family or historical holder
  subject_type    TEXT NOT NULL CHECK (subject_type IN ('asset','property')),
  subject_id      UUID NOT NULL,
  relationship    TEXT NOT NULL,             -- 'claimed_owner','co_holder','nominee','historical_holder'
  share_percent   NUMERIC(6,3),
  valid_from      DATE,
  valid_to        DATE,
  provenance_note TEXT NOT NULL DEFAULT 'family-reported, not verified against official records',
  verification    verify_status NOT NULL DEFAULT 'unverified',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON ownership_records (subject_type, subject_id);

-- Generic link table: documents <-> people/assets/properties/deadlines (FR-013).
CREATE TABLE links (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  from_type       TEXT NOT NULL,
  from_id         UUID NOT NULL,
  to_type         TEXT NOT NULL,
  to_id           UUID NOT NULL,
  link_type       TEXT NOT NULL DEFAULT 'relates_to',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (from_type, from_id, to_type, to_id, link_type)
);
CREATE INDEX ON links (family_id, from_type, from_id);
CREATE INDEX ON links (family_id, to_type, to_id);

-- ---------------------------------------------------------------- deadlines
CREATE TABLE deadlines (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  title           TEXT NOT NULL,
  description     TEXT,
  due_date        DATE NOT NULL,
  priority        priority_level NOT NULL DEFAULT 'medium',
  status          deadline_status NOT NULL DEFAULT 'open',
  recurrence_rule TEXT,                      -- RFC 5545 RRULE, NULL if one-off
  source_type     TEXT,                      -- 'document','asset','property','manual'
  source_id       UUID,
  assigned_to     UUID REFERENCES family_members(id) ON DELETE SET NULL,
  completed_at    TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON deadlines (family_id, status, due_date);

CREATE TABLE reminders (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  deadline_id     UUID NOT NULL REFERENCES deadlines(id) ON DELETE CASCADE,
  remind_at       TIMESTAMPTZ NOT NULL,
  channel         TEXT NOT NULL DEFAULT 'email',
  recipient_user  UUID REFERENCES users(id) ON DELETE CASCADE,
  delivery_status TEXT NOT NULL DEFAULT 'pending',
  attempts        INT NOT NULL DEFAULT 0,
  sent_at         TIMESTAMPTZ,
  error_message   TEXT
);
CREATE INDEX ON reminders (remind_at) WHERE delivery_status = 'pending';

-- ---------------------------------------------------------------- legacy (P1)
CREATE TABLE legacy_entries (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  author_member   UUID REFERENCES family_members(id) ON DELETE SET NULL,
  title           TEXT NOT NULL,
  body            TEXT,
  audio_key       TEXT,
  transcript      TEXT,
  about_type      TEXT,
  about_id        UUID,
  release_policy  TEXT NOT NULL DEFAULT 'immediate',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- security
CREATE TABLE permissions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  member_id       UUID NOT NULL REFERENCES family_members(id) ON DELETE CASCADE,
  resource_type   TEXT NOT NULL,             -- 'document','asset','property','*'
  resource_id     UUID,                      -- NULL = all of that type
  access          access_level NOT NULL,
  granted_by      UUID REFERENCES users(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (member_id, resource_type, resource_id)
);

CREATE TABLE audit_logs (
  id              BIGSERIAL PRIMARY KEY,
  family_id       UUID,
  actor_user_id   UUID,
  action          TEXT NOT NULL,             -- 'document.view','document.download','permission.grant'
  resource_type   TEXT,
  resource_id     UUID,
  ip_address      INET,
  user_agent      TEXT,
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON audit_logs (family_id, created_at DESC);
CREATE INDEX ON audit_logs (resource_type, resource_id);

CREATE TABLE ai_conversations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  query           TEXT NOT NULL,
  answer          TEXT,
  retrieved_ids   JSONB NOT NULL DEFAULT '[]'::jsonb,
  refused         BOOLEAN NOT NULL DEFAULT FALSE,
  model_name      TEXT,
  latency_ms      INT,
  token_usage     JSONB,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Consent + data-subject requests for DPDP Act compliance (Section 18).
CREATE TABLE consents (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  purpose         TEXT NOT NULL,             -- 'ai_processing','email_reminders','family_sharing'
  granted         BOOLEAN NOT NULL,
  notice_version  TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE data_requests (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind            TEXT NOT NULL,             -- 'export','erasure','correction'
  status          TEXT NOT NULL DEFAULT 'received',
  result_key      TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at    TIMESTAMPTZ
);

-- ---------------------------------------------------------------- auth & sessions
CREATE TABLE refresh_tokens (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash      TEXT NOT NULL UNIQUE,
  expires_at      TIMESTAMPTZ NOT NULL,
  revoked_at      TIMESTAMPTZ,
  user_agent      TEXT,
  ip_address      INET,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON refresh_tokens (user_id);
CREATE INDEX ON refresh_tokens (token_hash);

-- ---------------------------------------------------------------- background jobs
CREATE TABLE jobs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kind            TEXT NOT NULL,
  payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
  status          TEXT NOT NULL DEFAULT 'pending',
  attempts        INT NOT NULL DEFAULT 0,
  max_attempts    INT NOT NULL DEFAULT 3,
  run_after       TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_error      TEXT,
  locked_by       TEXT,
  locked_at       TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at    TIMESTAMPTZ
);
CREATE INDEX idx_jobs_poll ON jobs (run_after) WHERE status = 'pending';
CREATE INDEX idx_jobs_status ON jobs (status);

-- ---------------------------------------------------------------- notifications & reminders
CREATE TABLE notification_preferences (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
  channels           JSONB NOT NULL DEFAULT '["email"]'::jsonb,
  send_hour          INT NOT NULL DEFAULT 9 CHECK (send_hour >= 0 AND send_hour <= 23),
  timezone           TEXT NOT NULL DEFAULT 'Asia/Kolkata',
  muted_categories   JSONB NOT NULL DEFAULT '[]'::jsonb,
  weekly_digest      BOOLEAN NOT NULL DEFAULT FALSE,
  digest_day         INT NOT NULL DEFAULT 0 CHECK (digest_day >= 0 AND digest_day <= 6),
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON notification_preferences (user_id);

CREATE TABLE reminder_deliveries (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  reminder_id     UUID NOT NULL UNIQUE REFERENCES reminders(id) ON DELETE CASCADE,
  deadline_id     UUID NOT NULL REFERENCES deadlines(id) ON DELETE CASCADE,
  recipient_user  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  channel         TEXT NOT NULL DEFAULT 'email',
  sent_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON reminder_deliveries (recipient_user, sent_at);
CREATE UNIQUE INDEX idx_reminders_unique_schedule ON reminders (deadline_id, recipient_user, remind_at, channel);

-- ---------------------------------------------------------------- product analytics (Section 34)
CREATE TABLE events (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_name      TEXT NOT NULL,
  family_id       UUID REFERENCES families(id) ON DELETE CASCADE,
  user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
  properties      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON events (event_name, created_at);
CREATE INDEX ON events (family_id);



