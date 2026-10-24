# AgentGuard against the judging criteria

One page per criterion: what we claim, where to check it (a page, a command or a file, with the number), what it doesn't do yet, and what comes next. Every number below comes from a command in this repo.

**Two-minute version:** open [https://agent-harness-163s.vercel.app](https://agent-harness-163s.vercel.app), press **Open the dashboard**, and on **Business processes** press **Work today's inbox**. Approve the ₹4,500 refund, then press **Download evidence report**.

---

## 1. Reusability

**Claim.** AgentShield sits between *any* agent and *any* tools. A new process needs a YAML policy and a tool adapter, not new agent code.

| Evidence | Where |
|---|---|
| Five ways to connect an agent: Claude Code over MCP (no API key), any MCP client, Anthropic / OpenAI / LangGraph loops, a remote agent over HTTP, scripted agents | Site → **Integrate**; `agentguard run --harness …` |
| Your own REST system protected by one YAML file mapping routes to tools | `examples/payments_backend.yaml`; `agentguard protect --backend … --agent-id …` |
| Your own Python functions protected in about 60 lines, with policy, approval, blocks and a verified audit chain | `python examples/protect_your_tools.py` (tested in `tests/test_examples.py`) |
| The same gateway runs two business processes in two domains (Retail refunds, IT access) and 34 GuardBench tasks over 24 mock enterprise systems | Dashboard → **Business processes**, **GuardBench** |
| The same policy is enforced in testing (AgentGym, with injected faults) and in production (`protect`, `RuntimeSession`) | `docs/how-it-works.md` |

**Limits.** Tool adapters exist for HTTP/REST and Python. There are no ready-made connectors for ServiceNow, Okta or SAP yet; each is one YAML file of routes.

**Next.** Policy templates per process (refunds, access, payments), and a connector catalogue.

## 2. Governance and responsibility

**Claim.** The controls live outside the model, so they hold even when the model is wrong or manipulated. Every run produces evidence an auditor can check.

| Evidence | Where |
|---|---|
| Least privilege per agent: intake and reporting are read-only; only the action agent can refund or grant, up to its limit | Controls panel; `agentguard/shield/policies/default.yaml` |
| Human approval holds a call until a person decides; no answer means reject; a rejection is reported as an unfinished batch, not a success | Approve or reject the ₹4,500 refund; verdict `CORRECT_FAILURE_REPORTED` on reject |
| AI decisions checked by rules: Claude's decision stands only if the policy check agrees (18/18 agreed); otherwise a person decides | **Decisions: Claude + policy check** |
| Prompt injection: the injected ticket is labelled, withheld from the model and escalated | T-108, AR-209 |
| Data exfiltration tracked through base64, hex and split calls | Live run → `secret_exfiltration` → **Blocked actions** |
| Post-action verification against the system of record catches a tool's false "success" | `refund_false_success`, shield off against on |
| Tamper-evident audit: each event carries the hash of the previous one; editing one event fails verification at that event | `agentguard audit verify`; `tests/test_evidence.py` |
| **Evidence report per run:** agents, approvals (who, when, why), blocks, injections, verifications, the claim against the verdict, the hash-chain result and a framework mapping | **Download evidence report** on Business processes and Live run; `agentguard audit report <run>`; `GET /api/runs/{id}/evidence?format=md` |
| Mapping to the EU AI Act (Art. 12, 14, 15), NIST AI RMF, ISO/IEC 42001 and SOC 2 (CC6, CC7, CC8) | Site → **Trust** |

**Limits.** "Supports", not "certified": the evidence helps with these frameworks, but using AgentGuard does not by itself make a system compliant. Injection detection is explainable patterns, not a trained classifier, so policy, not detection, is the last line of defence.

**Next.** Signed evidence exports, named approvers with roles (SSO), and retention settings.

## 3. ROI and business value

**Claim.** Seven in ten cases are finished with no person involved. The costly mistakes that come from automating are prevented rather than paid for.

| Evidence | Where |
|---|---|
| 7 of 10 tickets (RefundOps) and 7 of 10 requests (AccessOps) resolved with no person; people see only exceptions, each with a reason | `agentguard ops run`; `agentguard ops run --process access` |
| ₹6,000 refunded and confirmed in the ledger, with the batch's claim graded against the real end state | Outcome report; verdict `CORRECT_SUCCESS` |
| 0 duplicate refunds and 0 false success claims with AgentShield on, against 3 and 3 with it off (75 runs each) | `agentguard benchmark --attempts 3`; Dashboard → **Benchmark** |
| About $0.02 of model cost per batch of 10 with Claude Sonnet | **Decision-making** panel |
| A calculator using those measured rates: with the defaults (4,400 cases a month, 8 minutes each, ₹500/hour, 1 costly mistake per 100 at ₹3,000), about 411 analyst hours and **₹2.97 lakh net a month** | Site → **ROI**; worked example in [roi.md](roi.md) |

**Limits.** The automation rate comes from two 10-case demo queues, and the other inputs are assumptions you set. Hosting, policy ownership and adapter work aren't in the calculator.

**Next.** Measure the rate on a real queue in shadow mode (decide, don't act) before switching actions on.

## 4. MVP readiness

**Claim.** It runs today: one command for each process, a dashboard, Docker, a public link, and tests.

| Evidence | Where |
|---|---|
| A public link with no server: the site at `/` and the dashboard at `/app/` replay 524 recorded real runs, including Claude runs, approvals and evidence downloads | The Vercel deployment; `scripts/build_static.sh` |
| Local in five minutes: `pip install -e .`, `agentguard ops run`, `agentguard serve` | Site → **Run it** |
| `docker compose up --build` | `Dockerfile`, `docker-compose.yml` |
| Production mode: a real HTTP backend behind AgentShield over MCP, with approvals in the dashboard | `agentguard protect` |
| 293 automated tests; 28 scenarios, each checked so that a do-nothing agent fails and the reference agent passes; 34 benchmark tasks with a validation gate | `pytest -q`; `agentguard validate-scenarios`; `agentguard bench validate` |
| Claude as the decision maker with a fallback: if the model is unavailable, the rules decide and the report says so | `--decider claude` |

**Limits.** It runs as a single node on SQLite. The store uses SQLModel and takes any database URL through `AGENTGUARD_DB_URL`, but only SQLite is tested. The public link is a recording; live runs need `agentguard serve`. There are no user accounts yet.

**Next.** A hosted live backend, authentication and roles for approvers, and Postgres as the default.

## 5. Originality and innovation

**Claim.** Each technique has prior art, but no tool we reviewed combines them. One gateway is both the test harness and the runtime enforcement point.

| What's new | Closest prior work | Where to see it |
|---|---|---|
| **Honesty is measured:** the verdict compares what the agent *claimed* with what changed (`INCORRECT_SUCCESS_CLAIM`) | τ-bench and AgentDojo grade the end state, not the claim | `refund_false_success` |
| **Faults after the side effect:** a timeout after the refund committed, a tool that reports false success, stale reads (11 seeded fault types) | Benchmarks inject hostile content, not lying tools | `agentguard benchmark` |
| **Data followed through encodings** (base64, hex, split calls) to any external sink | Invariant matches call order, not transformed data | `secret_exfiltration` |
| **One gateway for testing and production**, with human approval in both | Guardrail products run at runtime; benchmarks run offline | `RuntimeSession`, `protect` |
| **Incidents become validated tests:** a blocked run becomes a replayable scenario, kept only if a do-nothing agent fails it and the reference passes | LangSmith adds traces to datasets without validation | **Promote to regression** |
| **GuardBench:** 34 ITSMBench-style tickets, each with a documented trap and do-no-harm checks, run *through* the shield. With the shield on, Sonnet's solve rate falls 3 points (59% to 56%, one task) and it costs 31% less. | ITSMBench (89 tasks) measures agents without a protection layer | Dashboard → **GuardBench** |

**Limits.** The security test suite is small next to AgentDojo (629 cases) and InjecAgent (1,054). There is no user simulator like τ-bench's. Sources and full comparison: [novelty.md](novelty.md).

**Next.** Import AgentDojo's attacks as scenarios, and add a red-team page.
