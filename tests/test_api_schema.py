from agentguard.api import create_app


def test_openapi_schema_exposes_gateway_routes() -> None:
    schema = create_app().openapi()

    assert schema["info"]["title"] == "AgentGuard"
    assert "/v1/tool-calls" in schema["paths"]
    assert "/v1/tool-calls/{request_id}/approval" in schema["paths"]
    assert "/v1/audit/events" in schema["paths"]
