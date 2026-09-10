from __future__ import annotations

import httpx

from agentguard.models import DecisionAction, PolicyDecision, ToolCallRequest


class PolicyUnavailableError(RuntimeError):
    """Raised when OPA cannot make a valid decision."""


class OpaPolicyClient:
    def __init__(self, base_url: str, timeout_seconds: float = 2.0) -> None:
        self._url = f"{base_url.rstrip('/')}/v1/data/agentguard/tool_call/decision"
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    async def evaluate(self, request: ToolCallRequest, risk_signals: list[str]) -> PolicyDecision:
        payload = {
            "input": {
                "request": request.model_dump(mode="json"),
                "risk": {"signals": risk_signals},
            }
        }
        try:
            response = await self._client.post(self._url, json=payload)
            response.raise_for_status()
            result = response.json().get("result")
            if not isinstance(result, dict):
                raise PolicyUnavailableError("OPA returned no decision")
            return PolicyDecision.model_validate(result)
        except (httpx.HTTPError, ValueError) as exc:
            raise PolicyUnavailableError("OPA policy evaluation failed") from exc


class FailClosedPolicy:
    """Decorator that converts policy-engine failure into an explicit block."""

    def __init__(self, client: OpaPolicyClient) -> None:
        self._client = client

    async def close(self) -> None:
        await self._client.close()

    async def evaluate(self, request: ToolCallRequest, risk_signals: list[str]) -> PolicyDecision:
        try:
            return await self._client.evaluate(request, risk_signals)
        except PolicyUnavailableError:
            return PolicyDecision(
                action=DecisionAction.BLOCK,
                reason="Policy engine unavailable; request blocked fail-closed",
                policy_id="agentguard.fail_closed",
            )
