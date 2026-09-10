from __future__ import annotations

from typing import Protocol
from uuid import UUID

from agentguard.models import PolicyDecision, RequestStatus, SubmissionResponse, ToolCallRequest
from agentguard.repository import PostgresRepository
from agentguard.security import detect_risk_signals


class PolicyEvaluator(Protocol):
    async def evaluate(
        self, request: ToolCallRequest, risk_signals: list[str]
    ) -> PolicyDecision: ...


class GatewayService:
    def __init__(self, repository: PostgresRepository, policy: PolicyEvaluator) -> None:
        self._repository = repository
        self._policy = policy

    async def submit(self, request: ToolCallRequest, idempotency_key: str) -> SubmissionResponse:
        risk_signals = detect_risk_signals(request.arguments, request.context)
        decision = await self._policy.evaluate(request, risk_signals)
        return await self._repository.submit(
            request=request,
            idempotency_key=idempotency_key,
            decision=decision,
            risk_signals=risk_signals,
        )

    async def approve(
        self, request_id: UUID, *, approved: bool, reviewer: str, reason: str
    ) -> RequestStatus:
        return await self._repository.decide_approval(
            request_id, approved=approved, reviewer=reviewer, reason=reason
        )
