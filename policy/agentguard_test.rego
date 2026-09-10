package agentguard.tool_call_test

import data.agentguard.tool_call
import rego.v1

test_safe_read_is_allowed if {
    result := tool_call.decision with input as {
        "request": {"tool_name": "search.query"},
        "risk": {"signals": []},
    }
    result == {
        "action": "allow",
        "reason": "Low-risk tool is allowed by policy",
        "policy_id": "agentguard.tool_call.v1",
    }
}

test_sensitive_write_requires_approval if {
    result := tool_call.decision with input as {
        "request": {"tool_name": "email.send"},
        "risk": {"signals": []},
    }
    result.action == "require_approval"
}

test_prompt_injection_is_blocked if {
    result := tool_call.decision with input as {
        "request": {"tool_name": "search.query"},
        "risk": {"signals": ["prompt_injection"]},
    }
    result.action == "block"
}

test_data_exfiltration_is_blocked if {
    result := tool_call.decision with input as {
        "request": {"tool_name": "email.send"},
        "risk": {"signals": ["data_exfiltration"]},
    }
    result.action == "block"
}

test_unknown_tool_is_blocked if {
    result := tool_call.decision with input as {
        "request": {"tool_name": "unknown.tool"},
        "risk": {"signals": []},
    }
    result.action == "block"
}
