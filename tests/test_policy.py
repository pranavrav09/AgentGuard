import httpx
import pytest

from agentguard.models import DecisionAction, ToolCallRequest
from agentguard.policy import FailClosedPolicy, OpaPolicyClient, PolicyUnavailableError


class UnavailablePolicy:
    async def evaluate(self, request: ToolCallRequest, risk_signals: list[str]):
        raise PolicyUnavailableError("offline")

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_policy_failure_blocks_fail_closed() -> None:
    policy = FailClosedPolicy(UnavailablePolicy())  # type: ignore[arg-type]
    decision = await policy.evaluate(
        ToolCallRequest(agent_id="researcher", tool_name="search.query"), []
    )
    assert decision.action is DecisionAction.BLOCK
    assert decision.policy_id == "agentguard.fail_closed"


@pytest.mark.asyncio
async def test_opa_response_is_validated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/data/agentguard/tool_call/decision"
        return httpx.Response(
            200,
            json={
                "result": {
                    "action": "require_approval",
                    "reason": "review needed",
                    "policy_id": "test.v1",
                }
            },
        )

    client = OpaPolicyClient("http://opa.test")
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        decision = await client.evaluate(
            ToolCallRequest(agent_id="writer", tool_name="email.send"), []
        )
    finally:
        await client.close()
    assert decision.action is DecisionAction.REQUIRE_APPROVAL
