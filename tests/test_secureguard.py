from uuid import uuid4

import pytest

from agentguard.models import Job
from agentguard.secureguard import SecureGuard


def make_job(tool_name: str, arguments: dict[str, object] | None = None) -> Job:
    return Job(
        id=uuid4(),
        request_id=uuid4(),
        tool_name=tool_name,
        arguments=arguments or {},
        lease_token=uuid4(),
        attempt_count=1,
    )


@pytest.mark.asyncio
async def test_registered_tool_is_delivered() -> None:
    result = await SecureGuard().execute(make_job("search.query", {"query": "OPA Rego"}))
    assert result["ok"] is True
    assert result["query"] == "OPA Rego"


@pytest.mark.asyncio
async def test_unknown_tool_never_falls_through_to_execution() -> None:
    with pytest.raises(ValueError, match="no registered handler"):
        await SecureGuard().execute(make_job("python.eval", {"code": "print('unsafe')"}))
