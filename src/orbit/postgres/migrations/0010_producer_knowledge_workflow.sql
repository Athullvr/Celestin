-- Durable Celestin-owned delivery receipts and Capture revision metadata.
-- This does not authenticate an external producer or register producer identities.

DO $$
DECLARE
    role_row RECORD;
BEGIN
    SELECT rolcanlogin, rolsuper, rolbypassrls, rolcreaterole,
           rolcreatedb, rolreplication, rolinherit, oid
      INTO role_row
      FROM pg_catalog.pg_roles
     WHERE rolname = 'celestin_project_capture_runtime';
    IF NOT FOUND OR role_row.rolcanlogin OR role_row.rolsuper
       OR role_row.rolbypassrls OR role_row.rolcreaterole
       OR role_row.rolcreatedb OR role_row.rolreplication
       OR NOT role_row.rolinherit
       OR EXISTS (
           SELECT 1 FROM pg_catalog.pg_auth_members
            WHERE member = role_row.oid
       ) THEN
        RAISE EXCEPTION 'required Celestin group role is missing or unsafe: celestin_project_capture_runtime';
    END IF;
END;
$$;

CREATE TABLE celestin_producer_delivery_receipts (
    workspace_id           UUID NOT NULL,
    project_id             UUID NOT NULL,
    producer_id            TEXT COLLATE "C" NOT NULL,
    source_namespace       TEXT COLLATE "C" NOT NULL,
    delivery_id            TEXT COLLATE "C" NOT NULL CHECK (length(delivery_id) > 0),
    schema_version         SMALLINT NOT NULL CHECK (schema_version = 1),
    payload_revision_id    TEXT COLLATE "C" NOT NULL CHECK (length(payload_revision_id) > 0),
    payload_hash_version   TEXT COLLATE "C" NOT NULL CHECK (
        payload_hash_version = 'celestin-producer-delivery-v1+jcs-rfc8785+sha256'
    ),
    payload_hash           TEXT COLLATE "C" NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    payload_json           JSONB NOT NULL CHECK (jsonb_typeof(payload_json) = 'object'),
    receipt_outcome        JSONB NOT NULL CHECK (jsonb_typeof(receipt_outcome) = 'object'),
    received_by_kind       TEXT COLLATE "C" NOT NULL CHECK (received_by_kind IN ('human', 'service')),
    received_by_issuer     TEXT COLLATE "C" NOT NULL CHECK (length(received_by_issuer) > 0),
    received_by_subject    TEXT COLLATE "C" NOT NULL CHECK (length(received_by_subject) > 0),
    received_by_user_id    UUID,
    received_by_service_identity_id UUID,
    received_at            TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (workspace_id, project_id, producer_id, source_namespace, delivery_id),
    FOREIGN KEY (workspace_id, project_id, producer_id)
        REFERENCES celestin_project_producers(workspace_id, project_id, producer_id)
        ON DELETE RESTRICT,
    FOREIGN KEY (workspace_id, project_id, source_namespace)
        REFERENCES celestin_project_source_namespaces(workspace_id, project_id, source_namespace)
        ON DELETE RESTRICT,
    FOREIGN KEY (workspace_id, project_id)
        REFERENCES celestin_projects(workspace_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (workspace_id, received_by_user_id)
        REFERENCES celestin_workspace_memberships(workspace_id, user_id) ON DELETE RESTRICT,
    FOREIGN KEY (workspace_id, received_by_service_identity_id)
        REFERENCES celestin_service_identities(workspace_id, id) ON DELETE RESTRICT,
    CHECK (
        (received_by_kind = 'human'
            AND received_by_user_id IS NOT NULL
            AND received_by_service_identity_id IS NULL)
        OR
        (received_by_kind = 'service'
            AND received_by_user_id IS NULL
            AND received_by_service_identity_id IS NOT NULL)
    )
);

CREATE TABLE celestin_candidate_revision_payloads (
    workspace_id       UUID NOT NULL,
    project_id         UUID NOT NULL,
    producer_id        TEXT COLLATE "C" NOT NULL,
    candidate_id       TEXT COLLATE "C" NOT NULL,
    candidate_revision INTEGER NOT NULL,
    capture_state      JSONB NOT NULL CHECK (jsonb_typeof(capture_state) = 'object'),
    PRIMARY KEY (workspace_id, project_id, producer_id, candidate_id, candidate_revision),
    FOREIGN KEY (workspace_id, project_id, producer_id, candidate_id, candidate_revision)
        REFERENCES celestin_candidate_revisions(
            workspace_id, project_id, producer_id, candidate_id, candidate_revision
        ) ON DELETE RESTRICT
);

CREATE TABLE celestin_delivery_candidate_revisions (
    workspace_id          UUID NOT NULL,
    project_id            UUID NOT NULL,
    producer_id           TEXT COLLATE "C" NOT NULL,
    source_namespace      TEXT COLLATE "C" NOT NULL,
    delivery_id           TEXT COLLATE "C" NOT NULL,
    candidate_id          TEXT COLLATE "C" NOT NULL,
    candidate_revision    INTEGER NOT NULL,
    first_occurrence_ordinal INTEGER NOT NULL CHECK (first_occurrence_ordinal >= 0),
    PRIMARY KEY (
        workspace_id, project_id, producer_id, source_namespace, delivery_id, candidate_id
    ),
    FOREIGN KEY (workspace_id, project_id, producer_id, source_namespace, delivery_id)
        REFERENCES celestin_producer_delivery_receipts(
            workspace_id, project_id, producer_id, source_namespace, delivery_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (workspace_id, project_id, producer_id, candidate_id, candidate_revision)
        REFERENCES celestin_candidate_revisions(
            workspace_id, project_id, producer_id, candidate_id, candidate_revision
        ) ON DELETE RESTRICT
);

ALTER TABLE celestin_producer_delivery_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE celestin_producer_delivery_receipts FORCE ROW LEVEL SECURITY;
ALTER TABLE celestin_candidate_revision_payloads ENABLE ROW LEVEL SECURITY;
ALTER TABLE celestin_candidate_revision_payloads FORCE ROW LEVEL SECURITY;
ALTER TABLE celestin_delivery_candidate_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE celestin_delivery_candidate_revisions FORCE ROW LEVEL SECURITY;

CREATE INDEX idx_celestin_knowledge_claim_fts
    ON celestin_knowledge_records
    USING GIN (to_tsvector('simple'::regconfig, claim))
    WHERE lifecycle_status = 'current';

CREATE POLICY celestin_capture_scope_map_select
    ON celestin_private.project_runtime_scopes
    FOR SELECT TO celestin_project_capture_runtime
    USING (login_role_name = session_user::name);
GRANT USAGE ON SCHEMA celestin_private TO celestin_project_capture_runtime;
GRANT SELECT ON celestin_private.project_runtime_scopes TO celestin_project_capture_runtime;
GRANT EXECUTE ON FUNCTION public.celestin_request_scope_matches(UUID, UUID)
    TO celestin_project_capture_runtime;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'celestin_knowledge_records', 'celestin_evidence_records',
        'celestin_project_producers', 'celestin_project_source_namespaces',
        'celestin_candidates', 'celestin_candidate_revisions',
        'celestin_candidate_review_events', 'celestin_candidate_evidence_records',
        'celestin_candidate_occurrences', 'celestin_candidate_conversions',
        'celestin_producer_delivery_receipts', 'celestin_candidate_revision_payloads',
        'celestin_delivery_candidate_revisions'
    ] LOOP
        EXECUTE format(
            'CREATE POLICY celestin_capture_project_scope ON public.%I '
            'FOR ALL TO celestin_project_capture_runtime '
            'USING (public.celestin_request_scope_matches(workspace_id, project_id)) '
            'WITH CHECK (public.celestin_request_scope_matches(workspace_id, project_id))',
            table_name
        );
    END LOOP;
END;
$$;

GRANT USAGE ON SCHEMA public TO celestin_project_capture_runtime;
GRANT SELECT ON TABLE
    public.celestin_knowledge_records, public.celestin_evidence_records,
    public.celestin_project_producers, public.celestin_project_source_namespaces,
    public.celestin_candidates, public.celestin_candidate_revisions,
    public.celestin_candidate_review_events, public.celestin_candidate_evidence_records,
    public.celestin_candidate_occurrences, public.celestin_candidate_conversions,
    public.celestin_producer_delivery_receipts, public.celestin_candidate_revision_payloads,
    public.celestin_delivery_candidate_revisions
TO celestin_project_capture_runtime;
GRANT INSERT ON TABLE
    public.celestin_knowledge_records, public.celestin_evidence_records,
    public.celestin_candidates, public.celestin_candidate_revisions,
    public.celestin_candidate_review_events, public.celestin_candidate_evidence_records,
    public.celestin_candidate_occurrences, public.celestin_candidate_conversions,
    public.celestin_producer_delivery_receipts, public.celestin_candidate_revision_payloads,
    public.celestin_delivery_candidate_revisions
TO celestin_project_capture_runtime;

REVOKE ALL ON TABLE
    public.celestin_producer_delivery_receipts,
    public.celestin_candidate_revision_payloads,
    public.celestin_delivery_candidate_revisions
FROM PUBLIC, celestin_project_runtime, celestin_authorization_reader, celestin_authorization_admin;
