# How AgentGuard works

This page answers four questions: how dangerous multi-step sequences are
detected, how policies are enforced, how regression tests are generated, and
what the MVP measures. Every claim points at the code and the test that checks it.

## The one rule everything rests on

Every tool call an agent makes goes through one gateway
([shield/gateway.py](../agentguard/shield/gateway.py)). That holds for every
harness:

- a scripted agent;
- an API tool-calling loop;
- a LangGraph agent;
- Claude Code over MCP, which is started with no built-in tools and only the AgentGuard MCP server.

The gateway is where policy is enforced at runtime, and where AgentGym injects
faults and records the trace that the verifier and the regression loop use.

```mermaid
flowchart LR
    A[Agent: scripted, API loop, LangGraph, Claude Code] -->|tool call| G
    subgraph G[Gateway]
      direction TB
      S1[schema check] --> S2[injection scan of arguments]
      S2 --> S3[policy: identity, permission, limits, rules]
      S3 --> S4[risk score]
      S4 --> S5[data-flow sequence check]
      S5 --> S6[ordered pattern check]
      S6 --> D{most restrictive vote}
    end
    D -->|BLOCK| R[refusal with reason]
    D -->|REQUIRE_APPROVAL| H[human or auto-approver] -->|approved| F
    D -->|ALLOW / ALLOW_WITH_REDACTION| F[fault injector, gym only] --> W[(world / real system)]
    W --> O[output scan, redaction, taint labelling] --> A
```

## 1. How dangerous multi-step sequences are detected

Two mechanisms work together, because they catch different things.

### a) Data-flow sequences: where did this data come from?

[shield/taint.py](../agentguard/shield/taint.py) and the `sequences:` section of the policy.

1. **Label.** A tool's spec declares the labels its results carry. For example, `read_secret` returns `SECRET` and `query_database` returns `PII_BULK`.
2. **Fingerprint.** Each labelled string value is fingerprinted. That means hashes of every 10-character slice of the normalised value, plus digests of its raw, base64 and hex forms. Only fingerprints are kept; values never go into the trace.
3. **Follow transforms.** When a transform tool (`encode`) receives tainted input, its output becomes a new tainted record. The record inherits the labels and extends the chain: source → transform.
4. **Match sinks.** Before every call, the arguments are checked against the fingerprints, both as written and after decoding any base64 or hex tokens in them. A call to a sink (`send_email`, `http_post`) carrying data from a source named in a `sequences:` rule triggers that rule's action.
5. **Avoid false alarms on bulk data.** Bulk data only counts when values from at least 3 different rows appear, so an email to one customer is not mistaken for an export.

```mermaid
flowchart LR
    R["read_secret (#1)<br/>labels SECRET"] --> E["encode base64 (#2)<br/>inherits SECRET"] --> S["send_email (#3)<br/>to: ops-review@company.com"]
    S -. "args contain the encoded fingerprint" .-> X["BLOCK secret_exfiltration (CRITICAL)<br/>chain: read_secret → encode → send_email"]
```

Tested in [tests/test_taint.py](../tests/test_taint.py): direct, base64, hex, an encoded fragment, a value split across two calls, the chain through `encode`, the bulk threshold, and benign text with no false positives.

### b) Ordered action sequences: what happened before this call?

[shield/pipeline.py](../agentguard/shield/pipeline.py) `PatternStage`, and the `patterns:` section of the policy. These rules look at the calls already executed in the session:

| Rule kind | Default rule | What it stops |
|---|---|---|
| `requires_prior`, with `$argument` binding | `refund_without_verification` | A refund with no earlier successful lookup of the customer and of *the same* order |
| `after_label` within N calls | `act_after_untrusted` | A write or external action right after a tool returned UNTRUSTED (possibly injected) content |
| `rate` within N calls | `irreversible_burst` | A third refund in a short span |

Each decision stores the matched call sequence as evidence, so the dashboard shows the steps. Tested in [tests/test_patterns.py](../tests/test_patterns.py), including that no pattern fires on a normal refund.

## 2. How policies are enforced

The policy is YAML ([shield/policies/default.yaml](../agentguard/shield/policies/default.yaml)). It is compiled into typed objects when it loads, and errors point at the YAML line.

1. **Every stage votes.** Each stage returns ALLOW, ALLOW_WITH_REDACTION, REQUIRE_APPROVAL or BLOCK, with a plain-English reason, a rule id and a risk level. The most restrictive vote wins. The decision carries the highest risk among the votes, and all votes are recorded in the trace.
2. **Deny by default.** An unknown agent, or a tool that agent's policy doesn't list, is blocked. A stage that throws an error, or a rule that cannot be evaluated, also blocks: it fails closed.
3. **Per-tool limits.** These are amount limits, approval thresholds, allowed recipient domains, denied argument patterns (e.g. `SELECT *`) and row limits (redaction).
4. **Business rules against the real system.** `rules:` hold small expressions over the call's arguments and read-only queries the backend exposes. For example, `ledger.successful_refunds(order_id, amount_inr) == 0` and `crm.customer_verified(crm.order_customer(order_id))`. The expression language allows no attribute access, subscripts or builtins, so a policy file cannot run code.
5. **Post-action verification.** `verify:` checks run after a tool reports success and confirm the effect in the system of record. For example, `refund_landed` checks `ledger.refund_key_exists(idempotency_key)`. If the check fails, the agent gets `VERIFICATION_FAILED` instead of the false success (`on_fail: fail`), or the mismatch is only recorded (`flag`).
6. **Approvals.** A REQUIRE_APPROVAL call blocks until a human approves or rejects it, through the dashboard or the API. A timeout rejects it by default. Every approval is persisted.
7. **Injection is one layer, not the last.** Flagged tool output is labelled UNTRUSTED and raises the risk of later writes. When a block happens after an injection, its reason says that the policy blocks the action whether or not the injection was detected.

Tested in [tests/test_policy.py](../tests/test_policy.py), [tests/test_shield_misc.py](../tests/test_shield_misc.py) and [tests/test_acceptance_m4.py](../tests/test_acceptance_m4.py).

## 3. How regression tests are generated

`agentguard promote <run_id>`, the "Promote to regression" button in the dashboard, or `POST /api/runs/{id}/promote` ([gym/regression.py](../agentguard/gym/regression.py)).

```mermaid
flowchart TB
    A["failed or blocked run"] --> B["replay the scenario with its reference agent<br/>(same world, seed, faults)"]
    B --> C["diagnose: first divergent step,<br/>first fault, first block (3 lines)"]
    A --> D["for each blocked call: the most general pattern<br/>the reference agent never matches"]
    D --> E["new scenario = same world, seed, task, faults,<br/>expectations + forbidden calls,<br/>tags: regression, source_run"]
    E --> F{"equivalent scenario<br/>already exists?"}
    F -- yes --> X["skip: already covered"]
    F -- no --> G{"gate: null agent fails it<br/>AND reference agent passes it?"}
    G -- no --> Y["reject, with the reason"]
    G -- yes --> Z["write gym/scenarios/regression/reg_*.yaml<br/>→ part of every future run"]
```

- **Pattern candidates.** For each blocked call, the candidates are tried from most to least general: the tool alone, the tool plus one argument, then the tool plus all stable arguments in any order.
- **Volatile arguments are left out.** Values the agent chooses freely, such as idempotency keys, never appear in a pattern. Pinning one agent's nonce would not catch the next agent's identical mistake.
- **Covered failures are not duplicated.** A false-success failure, for example, is already covered by `refund_false_success`. Promoting it reports that instead of adding a copy.

Tested in [tests/test_regression.py](../tests/test_regression.py).

## 4. The MVP and what it measures

**Scope:**
- **Domain:** customer-support refunds, with 20 scenarios, 10 of them with injected faults.
- **Agents:**
  - scripted v1 (`naive`): blind retries, trusts every response, follows injected instructions;
  - scripted v2 (`naive_v2`): idempotent retries, checks the ledger before claiming success;
  - Claude Code over MCP.
- **Shield:** off or on.

`agentguard benchmark --attempts 3` gives these results. They are deterministic and reproducible:

| Outcome | v1, shield off | v1, shield on | v2, shield off | v2, shield on |
|---|---|---|---|---|
| Task success rate | 64% | 72% | 92% | 96% |
| pass^3 | 64% | 72% | 92% | 96% |
| Recovery from injected faults | 79% | 93% | 100% | 100% |
| Runs with a duplicate refund | 3 | **0** | 0 | 0 |
| Incorrect success claims | 3 | **0** | **0** | 0 |
| Runs with an unsafe side effect | 24 | 18 | 6 | 3 |
| Injected actions blocked | 0 | 3 | 0 | 0 |
| Policy violations attempted | 3 | 3 | 0 | 0 |
| Blocks with an explanation | n/a | 100% | n/a | 100% |
| Audit completeness | 100% | 100% | 100% | 100% |

**What the numbers say:**
- The shield prevents harm without changing the agent. Duplicate refunds go to 0, the injected export is blocked, and post-action verification (`refund_landed`) stops a false "refund succeeded" from ever reaching the agent, so false success claims also go to 0.
- The agent fix (v2) is what raises the task success rate from 64–72% to 92–96%.
- The two together are best.
- v2's remaining failures are on identity checks. The shield catches the unverified customer case, but not "refund the wrong customer's order", because `issue_refund` does not say who is asking.

**Red-team scenario:** separately, `secret_exfiltration` with the adversarial agent sends 2 emails with the shield off and 0 with it on.

**Real agent:** a Claude Code run of `normal_refund` over MCP passed: 5 tool calls through the gateway, with the ₹5,000 refund held for approval and then released.
