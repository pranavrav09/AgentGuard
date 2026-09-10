import os

import pytest
import pytest_asyncio

from agentguard.models import DecisionAction, PolicyDecision, RequestStatus, ToolCallRequest
from agentguard.repository import (
    IdempotencyConflictError,
    PostgresRepository,
    StaleLeaseError,
)

DATABASE_URL = os.getenv("AGENTGUARD_TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="AGENTGUARD_TEST_DATABASE_URL is not set"),
]


@pytest_asyncio.fixture
async def repository() -> PostgresRepository:
    assert DATABASE_URL is not None
    repo = await PostgresRepository.connect(DATABASE_URL, max_job_attempts=3)
    await repo.migrate()
    async with repo._pool.acquire() as connection:
        await connection.execute(
            "TRUNCATE audit_events, jobs, tool_call_requests RESTART IDENTITY CASCADE"
        )
    yield repo
    await repo.close()


@pytest.mark.asyncio
async def test_idempotency_replays_without_duplicate_job(repository: PostgresRepository) -> None:
    request = ToolCallRequest(
        agent_id="researcher", tool_name="search.query", arguments={"query": "leases"}
    )
    decision = PolicyDecision(action=DecisionAction.ALLOW, reason="safe")

    first = await repository.submit(request, "same-key-123", decision, [])
    replay = await repository.submit(request, "same-key-123", decision, [])

    assert replay.request_id == first.request_id
    assert replay.idempotent_replay is True
    assert await repository._pool.fetchval("SELECT count(*) FROM jobs") == 1


@pytest.mark.asyncio
async def test_reused_key_with_different_body_conflicts(repository: PostgresRepository) -> None:
    decision = PolicyDecision(action=DecisionAction.ALLOW, reason="safe")
    first = ToolCallRequest(agent_id="a", tool_name="search.query", arguments={"query": "one"})
    second = ToolCallRequest(agent_id="a", tool_name="search.query", arguments={"query": "two"})
    await repository.submit(first, "conflict-key", decision, [])

    with pytest.raises(IdempotencyConflictError):
        await repository.submit(second, "conflict-key", decision, [])


@pytest.mark.asyncio
async def test_expired_lease_is_recovered_and_stale_ack_is_fenced(
    repository: PostgresRepository,
) -> None:
    request = ToolCallRequest(
        agent_id="researcher", tool_name="search.query", arguments={"query": "recovery"}
    )
    decision = PolicyDecision(action=DecisionAction.ALLOW, reason="safe")
    submitted = await repository.submit(request, "recovery-key", decision, [])

    abandoned = await repository.claim_job("worker-a", lease_seconds=0)
    recovered = await repository.claim_job("worker-b", lease_seconds=30)

    assert abandoned is not None
    assert recovered is not None
    assert recovered.id == abandoned.id
    assert recovered.arguments == {"query": "recovery"}
    assert recovered.lease_token != abandoned.lease_token
    with pytest.raises(StaleLeaseError):
        await repository.complete_job(abandoned, "worker-a", {"ok": True})
    await repository.complete_job(recovered, "worker-b", {"ok": True})
    status = await repository._pool.fetchval(
        "SELECT status FROM tool_call_requests WHERE id = $1", submitted.request_id
    )
    assert status == RequestStatus.COMPLETED.value
    events = await repository.list_audit_events()
    assert events[0].event_type == "tool_call_completed"
    assert events[0].details["result"] == {"ok": True}
