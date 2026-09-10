CREATE TABLE IF NOT EXISTS tool_call_requests (
    id UUID PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    body_hash CHAR(64) NOT NULL,
    agent_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    arguments JSONB NOT NULL DEFAULT '{}'::jsonb,
    context JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'approval_required', 'blocked', 'completed', 'failed')
    ),
    policy_action TEXT NOT NULL CHECK (
        policy_action IN ('allow', 'block', 'require_approval')
    ),
    policy_reason TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    risk_signals TEXT[] NOT NULL DEFAULT '{}',
    reviewed_by TEXT,
    review_reason TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY,
    request_id UUID NOT NULL UNIQUE REFERENCES tool_call_requests(id),
    tool_name TEXT NOT NULL,
    arguments JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'leased', 'succeeded', 'failed')
    ),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    leased_by TEXT,
    lease_token UUID,
    leased_until TIMESTAMPTZ,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts > 0),
    result JSONB,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS jobs_claimable_idx
    ON jobs (available_at, created_at)
    WHERE status IN ('pending', 'leased');

CREATE TABLE IF NOT EXISTS audit_events (
    id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL,
    request_id UUID REFERENCES tool_call_requests(id),
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    details JSONB NOT NULL,
    previous_hash CHAR(64),
    event_hash CHAR(64) NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS audit_events_request_id_idx
    ON audit_events (request_id, id DESC);

CREATE OR REPLACE FUNCTION reject_audit_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events;
CREATE TRIGGER audit_events_no_update
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();

