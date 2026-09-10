package agentguard.tool_call

import rego.v1

default decision := {
    "action": "block",
    "reason": "Tool is not present in the AgentGuard allowlist",
    "policy_id": "agentguard.tool_call.v1",
}

safe_tools := {
    "calendar.read",
    "filesystem.read",
    "search.query",
}

sensitive_tools := {
    "email.send",
    "filesystem.write",
    "shell.execute",
}

decision := {
    "action": "block",
    "reason": sprintf("Detected security signals: %s", [concat(", ", input.risk.signals)]),
    "policy_id": "agentguard.tool_call.v1",
} if {
    count(input.risk.signals) > 0
}

decision := {
    "action": "require_approval",
    "reason": "Sensitive tool requires an explicit human decision",
    "policy_id": "agentguard.tool_call.v1",
} if {
    count(input.risk.signals) == 0
    input.request.tool_name in sensitive_tools
}

decision := {
    "action": "allow",
    "reason": "Low-risk tool is allowed by policy",
    "policy_id": "agentguard.tool_call.v1",
} if {
    count(input.risk.signals) == 0
    input.request.tool_name in safe_tools
}

