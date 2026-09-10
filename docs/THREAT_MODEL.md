# AgentGuard threat model

## Assets

- Tool credentials and the data reachable through tool adapters
- Integrity of policy decisions and human approvals
- Availability and exactly-once *effects* of agent work
- Audit evidence used during incident response

## Trust boundaries

The agent and all request content are untrusted. FastAPI validates shape and size before
passing normalized input to OPA. OPA is the authorization boundary. PostgreSQL is trusted to
serialize idempotency and lease transitions. SecureGuard is the execution boundary and only
dispatches to handlers registered at startup. A human reviewer is trusted to validate held
mutations.

## Controls

| Threat | Control |
|---|---|
| Prompt injection in nested arguments | Pattern detector plus policy block and attack tests |
| Secret or file exfiltration | Exfiltration signals block before queue insertion |
| Policy service outage | Fail-closed decision |
| Duplicate client retries | Body-bound idempotency key serialized with an advisory lock |
| Worker crash after claim | Expiring PostgreSQL lease |
| Stale worker completion | Per-claim fencing token |
| Concurrent workers | `FOR UPDATE SKIP LOCKED` claim transaction |
| Audit tampering | Append-only trigger and SHA-256 hash chain |
| Arbitrary tool execution | Static SecureGuard handler registry |

## Residual risks

Pattern matching is a defense-in-depth signal, not a complete semantic prompt-injection
detector. Real adapters can create irreversible side effects; they must implement downstream
idempotency using the AgentGuard request ID. A database owner can disable triggers, so
production audit records should also be exported to immutable external storage. Human
approval quality depends on identity, authorization, and review UI controls not included in
this reference implementation.

