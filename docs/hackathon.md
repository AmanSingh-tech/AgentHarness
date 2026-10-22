# AgentGuard at AgentOps 2026

**Multi-agent systems that run real business processes, safe by construction, with the evidence to prove it.**

AgentGuard runs two business processes with multi-agent systems:

- **RefundOps** (Retail and Supply): customer refunds.
- **AccessOps** (IT Infrastructure): access requests.

Every action those agents take goes through one guarded gateway, **AgentShield**. It enforces permissions and business rules, stops prompt injection and data exfiltration, holds risky actions for a human, checks every effect against the system of record, and keeps a tamper-evident audit log.

The same agents are tested before deployment in **AgentGym**, which uses simulated worlds and injected faults. AgentGym grades the agents on what actually happened, not on what they said happened.

## The business process

| Stage | RefundOps (Retail and Supply) | AccessOps (IT Infrastructure) |
|---|---|---|
| **Data ingestion** | `intake_agent` reads every open support ticket and extracts the order, the amount and the intent | `access_intake_agent` reads every open access request |
| **Intelligent decision-making** | `decision_agent` checks identity, order ownership, the refundable amount and refund history. Outcomes: refund, refuse, escalate, ask for information, or route elsewhere | `access_decision_agent` checks employment status, who asked (manager or self-service), the role, existing access and segregation of duties |
| **Action execution** | `action_agent` refunds within limits, updates the ticket and emails the customer | `access_action_agent` grants exactly what was requested, with an expiry, and notifies people |
| **Outcome reporting** | `reporting_agent` re-checks every refund in the ledger and writes the report | `access_reporting_agent` re-checks every grant in the directory and writes the report |

Every decision carries a plain-English reason, so a customer, an auditor or a manager can see why.

### Who makes the decisions

The decision agent runs in one of two modes, chosen with `--decider` or in the dashboard:

- **`claude`** (AI decision-making). Claude reads every case in one batched call: the customer's own words plus the facts the agent looked up. It proposes a decision with reasons. The rule-based agent then gives a second opinion.
  - **They agree:** Claude's decision and explanation stand, followed by the policy check that confirmed it.
  - **They disagree:** the case goes to a person, with both views.
  - **Not sent to the model:** cases flagged as prompt injections, and names or email addresses. The model sees only the facts a decision needs.
  - **Model unavailable:** the rules decide, and the report says so.
- **`rules`**: a deterministic agent, used as the reproducible baseline.

Either way, the action agent can act only through the gateway, so every permission, rule and approval still applies.

## Business value

On a morning's inbox of 10 tickets (`agentguard ops run`):

- **Handled with no human involved:** 7 of 10 tickets.
  - 2 refunds (₹6,000), each confirmed in the ledger;
  - 4 refusals, each with the reason emailed to the customer;
  - 1 question routed to general support.
- **Waiting for the customer:** 1 ticket. The agent emailed them to ask for the missing order number.
- **Sent to people:**
  - 2 tickets escalated, each with its reason: a ₹18,000 refund over the team's limit goes to finance, and a ticket containing a prompt injection goes to security review.
  - 1 refund (₹4,500, above the ₹2,000 threshold) waited for a person to approve it in the dashboard.

On the IT queue of 10 access requests (`agentguard ops run --process access`):

- **Grants:** 3 made, all confirmed in the directory. The payments-platform admin grant waited for a human approval.
- **Denials:** 3, each with an explanation: a terminated employee, a role the system doesn't offer, and a segregation-of-duties conflict.
- **Closed:** 1 request was for access the employee already had.
- **Escalated:** 2: one to the employee's manager, and one to security, for an injected justification.
- **Waiting:** 1 request has no justification, and the requester was asked for one.

People see only the exceptions. Each one arrives with the reason it is an exception.

## Responsible-AI controls

Each control is enforced by the gateway, not by the agents, and each has an automated test.

| Control | How | Proven by |
|---|---|---|
| **Least privilege per agent** | Each agent has its own identity in the policy: intake and reporting agents are read-only; only the action agent can refund or grant, and only within limits | `tests/test_ops.py::test_each_agent_is_held_to_its_own_permissions` |
| **AI decisions are checked** | Claude's proposal stands only if the rule-based check agrees; disagreements go to a person, and the batch reports itself unfinished until then. Injected cases and personal data never reach the model | `tests/test_ai_decisions.py` |
| **Business rules outside the model** | Refund limits, verified customers only, no duplicate refunds; grants must match the request exactly, active employees only, segregation of duties, expiry limits | `tests/test_policy.py`, `tests/test_access_ops.py::test_shield_enforces_it_controls_even_if_an_agent_misbehaves` |
| **Human approval** | Refunds above ₹2,000 and admin access to critical systems wait in the dashboard until approved or rejected. A timeout rejects | `tests/test_server.py::test_refund_ops_with_a_human_approval` |
| **Prompt-injection defence in depth** | AgentShield labels injected tool output as untrusted, and the agents also check the text themselves. Policy blocks the dangerous action even if detection misses it | `tests/test_shield_misc.py`, the `injection_*` scenarios |
| **Data-exfiltration prevention** | Sensitive data is tracked through encodings (base64, hex, split across calls) up to any external sink | `tests/test_taint.py`, `tests/test_acceptance_m4.py` |
| **Post-action verification** | After a refund or a grant reports success, the system of record is checked. A false "success" never reaches the agent | `tests/test_production.py::test_false_success_is_caught_at_runtime_and_promoted` |
| **Honest reporting** | The agents' report is graded against the real end state. When a person rejects a step, the batch reports failure rather than success | `tests/test_ops.py::test_rejected_approval_is_reported_honestly` |
| **Tamper-evident audit** | Every event is hash-chained. Edits, deletions and truncation are detected | `tests/test_audit.py` |
| **Every incident becomes a test** | A blocked or failed run is promoted to a regression scenario, kept only if it is valid | `tests/test_regression.py` |

## Measured results

`agentguard benchmark --attempts 3` runs 25 refund scenarios (faults, injections, refusals) per combination:

| Outcome | v1 agent, shield off | v1 agent, shield on | v2 agent, shield off | v2 agent, shield on |
|---|---|---|---|---|
| Task success | 64% | 72% | 92% | 96% |
| Recovery from injected faults | 79% | 93% | 100% | 100% |
| Duplicate refunds | 3 | **0** | 0 | 0 |
| Incorrect success claims | 3 | **0** | 0 | 0 |
| Runs with an unsafe side effect | 24 | 18 | 6 | 3 |
| Blocks with an explanation | n/a | 100% | n/a | 100% |

The shield removes duplicate refunds and false success claims without changing the agent. A better agent (v2) raises the success rate. The two together give the best result.

**With Claude as the decision agent** (`agentguard ops run --decider claude --model sonnet`, one batched Claude Code call per process):

| | RefundOps | AccessOps |
|---|---|---|
| Cases sent to Claude (1 withheld as an injection) | 9 | 9 |
| Policy check agreed | 9 | 9 |
| Independent verdict | `CORRECT_SUCCESS` | `CORRECT_SUCCESS` |
| Time · model cost | about 12 s · $0.02 | about 15 s · $0.02 |

The safeguard has already earned its place. In an early run, the instructions told Claude that admin grants "need human approval", and Claude escalated a grant that policy allows. The policy check disagreed, so the case went to a person instead of being silently mis-handled. The batch also reported itself unfinished, as it should. The instructions were then clarified.

The same gateway also protects real agents. Claude Code (Sonnet and Opus) ran the scenarios over MCP, with Claude Code's built-in tools switched off, so every action went through the gateway.

## Demo script (about 7 minutes)

```bash
agentguard serve                     # http://127.0.0.1:8000
```

1. **Business processes → RefundOps → "Work today's inbox"** (2 minutes).
   - Point out the four agents and their tool calls streaming in, each labelled with its agent.
   - The ₹4,500 refund appears under "Waiting for your decision". Approve it.
   - The outcome report appears: refunds confirmed in the ledger, reasons for every decision, and the controls panel (1 human approval, 1 injection detected, verifications passed, audit chain verified).
   - The independent verdict reads `CORRECT_SUCCESS`.
   - Switch **Decisions** to **Claude + policy check** and run it again. Each reason now begins with Claude's explanation, each row is labelled "decided by claude:sonnet, policy check agrees", and the Decision-making panel shows 9 agreed, 0 disagreed, and T-108 withheld as an injection.
2. **Run it again and reject the approval** (30 seconds). The report says "stopped by controls". The batch reports the failure honestly, and the verdict reads `CORRECT_FAILURE_REPORTED`.
3. **Switch to AccessOps → "Work the access queue"** (1 minute). Approve the payments admin grant. Show the segregation-of-duties denial and the terminated employee.
4. **Live run → `secret_exfiltration` with the adversarial agent** (1 minute). **Blocked actions** shows `read_secret → encode → send_email` blocked, with the whole chain.
5. **Live run → `refund_false_success`, naive agent, shield off, then on** (1 minute).
   - Off: the verdict banner reads "❌ Agent incorrectly reported success".
   - On: post-action verification stops the lie before it reaches the agent.
6. **Benchmark** (1 minute): the v1/v2 × shield off/on charts.
7. **Promote to regression** on a blocked run (30 seconds): it becomes a new test, accepted only after the null/reference check.

Run this before the demo as a backup: `agentguard demo` and `agentguard ops run` in a terminal.

## Likely questions

- **Where is the AI?**
  - With `--decider claude`, Claude makes the decisions: it reads each ticket or request and explains its decision in plain language.
  - It isn't trusted blindly. A deterministic policy check must agree, otherwise a person decides. The gateway enforces limits and approvals whatever either of them decides.
  - Beyond the decision agent, AgentGuard is agent-agnostic: Claude Code over MCP, or API-based agents (`native:anthropic`, LangGraph), can run the work through the same gateway and are held to the same controls.
- **Why keep the rules at all?** They are the reproducible baseline, the second opinion that catches a model's mistakes, and the fallback when the model is unavailable.
- **What stops a compromised or hallucinating agent?**
  - The gateway, not the agent's good behaviour. Permissions, business rules, data-flow tracking and approvals sit outside the model.
  - `test_shield_enforces_it_controls_even_if_an_agent_misbehaves` drives the action agent to widen access, grant to the wrong person and break segregation of duties. Every one of those calls is blocked.
- **Does it work on a real system?**
  - Production mode puts the same gateway in front of a real REST service (`agentguard protect`, `examples/payments_service.py`), with post-action verification and cross-process approvals.
- **How is it different from guardrail products?**
  - See [novelty.md](novelty.md), which has cited comparisons.
  - In short: one choke point serves both testing and runtime, outcomes are graded by the world state, faults are injected after commit, data is tracked through encodings, and every incident becomes a validated regression test.
- **How do you know the numbers are right?** Every number comes from a command in this repository, and reruns are deterministic. CI runs the tests, the scenario validation, the demo and the audit verification on every push.
