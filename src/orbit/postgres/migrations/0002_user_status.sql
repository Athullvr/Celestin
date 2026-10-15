-- Existing identities must be explicitly activated after trusted verification.
-- The default is intentionally fail-closed for both backfilled and new users.
ALTER TABLE celestin_users
    ADD COLUMN status TEXT NOT NULL DEFAULT 'suspended';

ALTER TABLE celestin_users
    ADD CONSTRAINT celestin_users_status_check
    CHECK (status IN ('active', 'suspended'));
