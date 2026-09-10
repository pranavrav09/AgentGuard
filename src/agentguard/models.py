from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DecisionAction(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    REQUIRE_APPROVAL = "require_approval"


class RequestStatus(StrEnum):
    QUEUED = "queued"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


class ToolCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.:-]+$")
    tool_name: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.:-]+$")
    arguments: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("arguments", "context")
    @classmethod
    def limit_serialized_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        import json

        if len(json.dumps(value, separators=(",", ":"), default=str)) > 64_000:
            raise ValueError("serialized object must not exceed 64 KB")
        return value


class PolicyDecision(BaseModel):
    action: DecisionAction
    reason: str = Field(min_length=1, max_length=500)
    policy_id: str = "agentguard.tool_call"


class SubmissionResponse(BaseModel):
    request_id: UUID
    status: RequestStatus
    decision: PolicyDecision
    risk_signals: list[str]
    idempotent_replay: bool = False


class ApprovalRequest(BaseModel):
    approved: bool
    reviewer: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)


class ApprovalResponse(BaseModel):
    request_id: UUID
    status: RequestStatus


class AuditEvent(BaseModel):
    id: int
    occurred_at: datetime
    request_id: UUID | None
    event_type: str
    actor: str
    details: dict[str, Any]
    previous_hash: str | None
    event_hash: str


class Job(BaseModel):
    id: UUID
    request_id: UUID
    tool_name: str
    arguments: dict[str, Any]
    lease_token: UUID
    attempt_count: int
