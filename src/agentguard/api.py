import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status

from agentguard.config import Settings, get_settings
from agentguard.models import (
    ApprovalRequest,
    ApprovalResponse,
    AuditEvent,
    RequestStatus,
    SubmissionResponse,
    ToolCallRequest,
)
from agentguard.policy import FailClosedPolicy, OpaPolicyClient
from agentguard.repository import (
    IdempotencyConflictError,
    InvalidRequestStateError,
    PostgresRepository,
    RequestNotFoundError,
)
from agentguard.service import GatewayService

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repository = await PostgresRepository.connect(
            settings.database_url, settings.max_job_attempts
        )
        await repository.migrate()
        policy = FailClosedPolicy(OpaPolicyClient(settings.opa_url, settings.opa_timeout_seconds))
        app.state.repository = repository
        app.state.policy = policy
        app.state.gateway = GatewayService(repository, policy)
        try:
            yield
        finally:
            await policy.close()
            await repository.close()

    app = FastAPI(
        title="AgentGuard",
        version="0.1.0",
        description=(
            "A fail-closed policy gateway that mediates AI agent tool calls with OPA, "
            "human approvals, durable delivery, and tamper-evident audit events."
        ),
        lifespan=lifespan,
    )

    def gateway() -> GatewayService:
        return app.state.gateway

    def repository() -> PostgresRepository:
        return app.state.repository

    @app.get("/health", tags=["operations"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["operations"])
    async def ready(repo: Annotated[PostgresRepository, Depends(repository)]) -> dict[str, str]:
        if not await repo.is_ready():
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="not ready")
        return {"status": "ready"}

    @app.post(
        "/v1/tool-calls",
        response_model=SubmissionResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["gateway"],
    )
    async def submit_tool_call(
        request: ToolCallRequest,
        response: Response,
        service: Annotated[GatewayService, Depends(gateway)],
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", min_length=8, max_length=200),
        ],
    ) -> SubmissionResponse:
        try:
            result = await service.submit(request, idempotency_key)
        except IdempotencyConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        if result.status is RequestStatus.BLOCKED:
            response.status_code = status.HTTP_403_FORBIDDEN
        return result

    @app.post(
        "/v1/tool-calls/{request_id}/approval",
        response_model=ApprovalResponse,
        tags=["approvals"],
    )
    async def decide_approval(
        request_id: UUID,
        approval: ApprovalRequest,
        service: Annotated[GatewayService, Depends(gateway)],
    ) -> ApprovalResponse:
        try:
            request_status = await service.approve(
                request_id,
                approved=approval.approved,
                reviewer=approval.reviewer,
                reason=approval.reason,
            )
        except RequestNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="request not found"
            ) from exc
        except InvalidRequestStateError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return ApprovalResponse(request_id=request_id, status=request_status)

    @app.get("/v1/audit/events", response_model=list[AuditEvent], tags=["audit"])
    async def list_audit_events(
        repo: Annotated[PostgresRepository, Depends(repository)],
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[AuditEvent]:
        return await repo.list_audit_events(limit)

    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    uvicorn.run("agentguard.api:app", host="0.0.0.0", port=8000, reload=False)
