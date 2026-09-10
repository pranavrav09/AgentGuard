from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from agentguard.models import (
    AuditEvent,
    DecisionAction,
    Job,
    PolicyDecision,
    RequestStatus,
    SubmissionResponse,
    ToolCallRequest,
)


class IdempotencyConflictError(RuntimeError):
    pass


class RequestNotFoundError(RuntimeError):
    pass


class InvalidRequestStateError(RuntimeError):
    pass


class StaleLeaseError(RuntimeError):
    pass


def canonical_request_hash(request: ToolCallRequest) -> str:
    payload = json.dumps(
        request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class PostgresRepository:
    def __init__(self, pool: asyncpg.Pool, max_job_attempts: int = 5) -> None:
        self._pool = pool
        self._max_job_attempts = max_job_attempts

    @classmethod
    async def connect(cls, database_url: str, max_job_attempts: int = 5) -> PostgresRepository:
        pool = await asyncpg.create_pool(database_url, min_size=1, max_size=10, command_timeout=10)
        return cls(pool, max_job_attempts)

    async def close(self) -> None:
        await self._pool.close()

    async def migrate(self) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute("SELECT pg_advisory_lock(724813990)")
            try:
                migration_dir = resources.files("agentguard").joinpath("migrations")
                packaged = (
                    sorted(
                        (item for item in migration_dir.iterdir() if item.name.endswith(".sql")),
                        key=lambda item: item.name,
                    )
                    if migration_dir.is_dir()
                    else []
                )
                if packaged:
                    migrations = packaged
                else:
                    source_dir = Path(__file__).resolve().parents[2] / "migrations"
                    migrations = sorted(source_dir.glob("*.sql"))
                if not migrations:
                    raise RuntimeError("no database migrations found")
                for migration in migrations:
                    await connection.execute(migration.read_text())
            finally:
                await connection.execute("SELECT pg_advisory_unlock(724813990)")

    async def submit(
        self,
        request: ToolCallRequest,
        idempotency_key: str,
        decision: PolicyDecision,
        risk_signals: list[str],
    ) -> SubmissionResponse:
        body_hash = canonical_request_hash(request)
        request_id = uuid4()
        status = {
            DecisionAction.ALLOW: RequestStatus.QUEUED,
            DecisionAction.BLOCK: RequestStatus.BLOCKED,
            DecisionAction.REQUIRE_APPROVAL: RequestStatus.APPROVAL_REQUIRED,
        }[decision.action]

        async with self._pool.acquire() as connection, connection.transaction():
            # A transaction-scoped advisory lock serializes identical keys, avoiding a race
            # between the uniqueness check and side effects such as queue insertion.
            await connection.execute("SELECT pg_advisory_xact_lock(hashtext($1))", idempotency_key)
            existing = await connection.fetchrow(
                "SELECT * FROM tool_call_requests WHERE idempotency_key = $1", idempotency_key
            )
            if existing:
                if existing["body_hash"] != body_hash:
                    raise IdempotencyConflictError(
                        "idempotency key was already used with a different request body"
                    )
                return self._submission_from_record(existing, idempotent_replay=True)

            await connection.execute(
                """
                INSERT INTO tool_call_requests (
                    id, idempotency_key, body_hash, agent_id, tool_name, arguments,
                    context, status, policy_action, policy_reason, policy_id, risk_signals
                ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10, $11, $12)
                """,
                request_id,
                idempotency_key,
                body_hash,
                request.agent_id,
                request.tool_name,
                _json(request.arguments),
                _json(request.context),
                status.value,
                decision.action.value,
                decision.reason,
                decision.policy_id,
                risk_signals,
            )
            if decision.action is DecisionAction.ALLOW:
                await self._enqueue(connection, request_id)
            await self._append_audit(
                connection,
                request_id=request_id,
                event_type="policy_decision",
                actor=request.agent_id,
                details={
                    "action": decision.action.value,
                    "reason": decision.reason,
                    "policy_id": decision.policy_id,
                    "risk_signals": risk_signals,
                    "tool_name": request.tool_name,
                },
            )

        return SubmissionResponse(
            request_id=request_id,
            status=status,
            decision=decision,
            risk_signals=risk_signals,
        )

    async def decide_approval(
        self, request_id: UUID, *, approved: bool, reviewer: str, reason: str
    ) -> RequestStatus:
        async with self._pool.acquire() as connection, connection.transaction():
            record = await connection.fetchrow(
                "SELECT * FROM tool_call_requests WHERE id = $1 FOR UPDATE", request_id
            )
            if record is None:
                raise RequestNotFoundError(str(request_id))
            if record["status"] != RequestStatus.APPROVAL_REQUIRED.value:
                raise InvalidRequestStateError(
                    f"request is {record['status']}, not approval_required"
                )

            status = RequestStatus.QUEUED if approved else RequestStatus.BLOCKED
            await connection.execute(
                """
                UPDATE tool_call_requests
                SET status = $2, reviewed_by = $3, review_reason = $4,
                    reviewed_at = now(), updated_at = now()
                WHERE id = $1
                """,
                request_id,
                status.value,
                reviewer,
                reason,
            )
            if approved:
                await self._enqueue(connection, request_id)
            await self._append_audit(
                connection,
                request_id=request_id,
                event_type="human_approval",
                actor=reviewer,
                details={"approved": approved, "reason": reason},
            )
            return status

    async def claim_job(self, worker_id: str, lease_seconds: int) -> Job | None:
        lease_token = uuid4()
        async with self._pool.acquire() as connection, connection.transaction():
            record = await connection.fetchrow(
                """
                WITH candidate AS (
                    SELECT id
                    FROM jobs
                    WHERE (
                        (status = 'pending' AND available_at <= now())
                        OR (status = 'leased' AND leased_until < now())
                    )
                    AND attempt_count < max_attempts
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE jobs AS job
                SET status = 'leased', leased_by = $1, lease_token = $2,
                    leased_until = now() + make_interval(secs => $3),
                    attempt_count = attempt_count + 1, updated_at = now()
                FROM candidate
                WHERE job.id = candidate.id
                RETURNING job.*
                """,
                worker_id,
                lease_token,
                lease_seconds,
            )
            if record is None:
                return None
            await self._append_audit(
                connection,
                request_id=record["request_id"],
                event_type="job_leased",
                actor=worker_id,
                details={
                    "job_id": str(record["id"]),
                    "attempt_count": record["attempt_count"],
                    "lease_token": str(lease_token),
                },
            )
            return Job(
                id=record["id"],
                request_id=record["request_id"],
                tool_name=record["tool_name"],
                arguments=record["arguments"],
                lease_token=lease_token,
                attempt_count=record["attempt_count"],
            )

    async def complete_job(self, job: Job, worker_id: str, result: Mapping[str, Any]) -> None:
        async with self._pool.acquire() as connection, connection.transaction():
            updated = await connection.fetchrow(
                """
                UPDATE jobs
                SET status = 'succeeded', result = $3::jsonb, leased_until = NULL,
                    updated_at = now(), completed_at = now()
                WHERE id = $1 AND lease_token = $2 AND status = 'leased'
                RETURNING request_id
                """,
                job.id,
                job.lease_token,
                _json(result),
            )
            if updated is None:
                raise StaleLeaseError(f"lease no longer owns job {job.id}")
            await connection.execute(
                """
                UPDATE tool_call_requests
                SET status = 'completed', updated_at = now()
                WHERE id = $1
                """,
                job.request_id,
            )
            await self._append_audit(
                connection,
                request_id=job.request_id,
                event_type="tool_call_completed",
                actor=worker_id,
                details={"job_id": str(job.id), "result": result},
            )

    async def fail_job(self, job: Job, worker_id: str, error: str) -> bool:
        terminal = job.attempt_count >= self._max_job_attempts
        next_status = "failed" if terminal else "pending"
        # Capped exponential delay prevents hot-looping a repeatedly failing call.
        retry_delay = min(2**job.attempt_count, 60)
        async with self._pool.acquire() as connection, connection.transaction():
            updated = await connection.fetchrow(
                """
                UPDATE jobs
                SET status = $3, last_error = $4, lease_token = NULL, leased_by = NULL,
                    leased_until = NULL, available_at = now() + make_interval(secs => $5),
                    updated_at = now()
                WHERE id = $1 AND lease_token = $2 AND status = 'leased'
                RETURNING request_id
                """,
                job.id,
                job.lease_token,
                next_status,
                error[:1000],
                retry_delay,
            )
            if updated is None:
                raise StaleLeaseError(f"lease no longer owns job {job.id}")
            if terminal:
                await connection.execute(
                    """
                    UPDATE tool_call_requests
                    SET status = 'failed', updated_at = now()
                    WHERE id = $1
                    """,
                    job.request_id,
                )
            await self._append_audit(
                connection,
                request_id=job.request_id,
                event_type="tool_call_failed" if terminal else "tool_call_retry_scheduled",
                actor=worker_id,
                details={
                    "job_id": str(job.id),
                    "attempt_count": job.attempt_count,
                    "error": error[:1000],
                    "terminal": terminal,
                },
            )
        return terminal

    async def list_audit_events(self, limit: int = 100) -> list[AuditEvent]:
        async with self._pool.acquire() as connection:
            records = await connection.fetch(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT $1", limit
            )
        return [AuditEvent.model_validate(dict(record)) for record in records]

    async def is_ready(self) -> bool:
        try:
            return await self._pool.fetchval("SELECT 1") == 1
        except (asyncpg.PostgresError, OSError):
            return False

    async def _enqueue(self, connection: asyncpg.Connection, request_id: UUID) -> None:
        await connection.execute(
            """
            INSERT INTO jobs (id, request_id, tool_name, arguments, max_attempts)
            SELECT $2, id, tool_name, arguments, $3
            FROM tool_call_requests
            WHERE id = $1
            ON CONFLICT (request_id) DO NOTHING
            """,
            request_id,
            uuid4(),
            self._max_job_attempts,
        )

    async def _append_audit(
        self,
        connection: asyncpg.Connection,
        *,
        request_id: UUID | None,
        event_type: str,
        actor: str,
        details: Mapping[str, Any],
    ) -> None:
        # One small global critical section preserves a strict, verifiable hash chain.
        await connection.execute("SELECT pg_advisory_xact_lock(724813991)")
        previous_hash = await connection.fetchval(
            "SELECT event_hash FROM audit_events ORDER BY id DESC LIMIT 1"
        )
        occurred_at = datetime.now(UTC)
        canonical = _json(
            {
                "actor": actor,
                "details": details,
                "event_type": event_type,
                "occurred_at": occurred_at.isoformat(),
                "previous_hash": previous_hash,
                "request_id": str(request_id) if request_id else None,
            }
        )
        event_hash = hashlib.sha256(canonical.encode()).hexdigest()
        await connection.execute(
            """
            INSERT INTO audit_events (
                occurred_at, request_id, event_type, actor, details, previous_hash, event_hash
            ) VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
            """,
            occurred_at,
            request_id,
            event_type,
            actor,
            _json(details),
            previous_hash,
            event_hash,
        )

    @staticmethod
    def _submission_from_record(
        record: asyncpg.Record, idempotent_replay: bool
    ) -> SubmissionResponse:
        return SubmissionResponse(
            request_id=record["id"],
            status=RequestStatus(record["status"]),
            decision=PolicyDecision(
                action=DecisionAction(record["policy_action"]),
                reason=record["policy_reason"],
                policy_id=record["policy_id"],
            ),
            risk_signals=list(record["risk_signals"]),
            idempotent_replay=idempotent_replay,
        )
