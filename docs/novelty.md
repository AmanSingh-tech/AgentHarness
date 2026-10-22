# What is new in AgentGuard

AgentGuard tests and protects tool-using AI agents. Most of its individual
techniques already exist in published benchmarks or guardrail products. What
none of the tools reviewed here describe is the **combination**: one gateway
that is both the test harness and the runtime enforcement point, with
verified-outcome grading, post-commit fault injection, sequence-aware policy,
human approval, and an automatic, validated path from a runtime failure to a
regression test.

This page compares AgentGuard with the closest work. Claims about other tools
come from their own papers, docs or repositories (linked) as reviewed in
October 2026. "Not described" means the sources below do not mention it, not
that the tool cannot do it.

## The closest work

**Agent benchmarks**

- **τ-bench (Sierra).** A user simulator talks to an agent that has domain tools and policy documents (airline, retail). A task succeeds when the database at the end matches an annotated goal state. τ-bench introduced **pass^k**: the agent must succeed on all k independent attempts. AgentGuard uses pass^k directly. ([paper](https://arxiv.org/pdf/2406.12045), [Sierra blog](https://sierra.ai/blog/tau-bench-shaping-development-evaluation-agents))
- **AgentDojo (ETH Zurich, Invariant Labs).** 97 tasks and 629 security test cases over four environments. It is graded by formal checks over the environment state, not an LLM judge, and reports utility, utility under attack, and attack success rate. ([paper](https://arxiv.org/html/2406.13352v3))
- **InjecAgent (UIUC).** 1,054 indirect prompt-injection test cases across 17 user tools and 62 attacker tools. It covers direct harm and private-data exfiltration. ([paper](https://arxiv.org/html/2403.02691v3))
- **Inspect (UK AI Security Institute).** A general evaluation framework with an agent loop, built-in and MCP tools, and sandboxing on Docker, Kubernetes or Proxmox. ([AISI sandboxing post](https://aisi.gov.uk/blog/the-inspect-sandboxing-toolkit-scalable-and-secure-ai-agent-evaluations))

**Runtime guardrails**

- **Invariant Guardrails.** Rules over agent traces, with a flow operator (`->`) that matches ordered tool-call → tool-call and tool-output → tool-call patterns, e.g. `get_inbox` followed by `send_email` to an unknown address. Rules run in a gateway that proxies LLM and MCP requests ("before and after") or locally on traces. A match errors the request. ([repository](https://github.com/invariantlabs-ai/invariant))
- **NVIDIA NeMo Guardrails.** Input, retrieval, dialog, execution and output rails. Execution rails "validate tool inputs and outputs before and after invocation". ([docs](https://docs.nvidia.com/nemo/guardrails/latest/index.html))
- **Guardrails AI.** Composable validators (PII, toxicity, …) on LLM inputs and outputs that raise, repair or re-ask. ([docs](https://guardrailsai.com/docs/concepts/hub))
- **Meta Prompt Guard / Llama Guard.** Classifiers: Prompt Guard flags injection and jailbreak prompts, and Llama Guard classifies content against a hazard taxonomy. ([Prompt Guard 2 card](https://console.groq.com/docs/model/meta-llama/llama-prompt-guard-2-22m))
- **Lakera Guard.** A hosted API that screens messages for prompt injection and returns a flag. ([integration docs](https://docs.api7.ai/ai-gateway/traffic-controls/guardrails/lakera))

**Observability and regression**

- **LangSmith.** Adds production runs to datasets manually or through automation rules, then re-runs evaluators on those datasets before a change ships. ([LangChain blog](https://www.langchain.com/blog/langsmith-production-logging-automations))

## Capability comparison

✅ described in the sources · ◐ partly · — not described

| Capability | τ-bench | AgentDojo | InjecAgent | Invariant | NeMo | Guardrails AI / classifiers | LangSmith | **AgentGuard** |
|---|---|---|---|---|---|---|---|---|
| Grades by world state, not by an LLM judge | ✅ | ✅ | ◐ (attack = tool called) | — | — | — | ◐ (any evaluator) | ✅ snapshot diff + side-effect accounting |
| Separates *what the agent claimed* from *what happened* (e.g. "incorrect success claim") | — | — | — | — | — | — | — | ✅ |
| Injected tool faults (timeouts after commit, false success, stale reads, …) | — | — | — | — | — | — | — | ✅ 11 types, seeded |
| pass^k reliability | ✅ | — | — | — | — | — | — | ✅ |
| Prompt-injection test cases | — | ✅ | ✅ | — | — | — | — | ◐ (a few scenarios) |
| Runtime enforcement at a single choke point | — | — | — | ✅ gateway | ✅ rails | ◐ per call | — | ✅ gateway |
| Ordered tool-call sequence rules | — | — | — | ✅ flow operator | — | — | — | ✅ `patterns:` |
| Data flow tracked **through transformations** (base64, hex, split) | — | — | — | — | — | — | — | ✅ taint tracking |
| Human approval holds a call until someone decides | — | — | — | — | — | — | — | ✅ |
| Same component used in testing and at runtime | — | — | — | ◐ (rules on traces offline and at runtime) | — | — | — | ✅ |
| Runtime failure → regression test, automatically | — | — | — | — | — | — | ◐ (trace → dataset example) | ✅ replayed world + faults |
| Regression tests validated before acceptance | — | — | — | — | — | — | — | ✅ null must fail, reference must pass |

## Where AgentGuard is new

1. **Claim honesty as a measured outcome.** The verifier never takes the agent's message as evidence. It diffs the world's snapshots, then compares the agent's claim with that evidence. That separates *the task failed* from *the agent said it succeeded when it did not* (`INCORRECT_SUCCESS_CLAIM`), which is the failure that hurts most in enterprise workflows.
2. **Faults after the side effect.** `timeout_after_commit`, `false_success` and `stale_read` test what an agent does when a tool lies about an irreversible action. This is where duplicate refunds and false success claims come from. The benchmarks reviewed inject adversarial *content*, not failures of the tools themselves.
3. **Data flow through transformations.** AgentShield fingerprints sensitive results: normalised substrings, plus digests of the raw, base64 and hex forms. It follows them through `encode`-style transforms and decodes arguments, so `read_secret → encode → send_email` and a secret split across two emails are both caught. Invariant's flow rules match ordered events. The sources reviewed do not describe tracking a value through encodings.
4. **One choke point for testing and production.** The same gateway, policy and approvals run inside AgentGym (with faults) and at runtime (without). So a policy that passes the benchmark is the policy that ships.
5. **A closed, gated regression loop.** A blocked or failed run is promoted to a scenario that replays the same world, seed and faults. The forbidden pattern is the most general one the reference agent never matches. The scenario is accepted only if the null agent fails it and the reference agent passes it. LangSmith turns traces into dataset examples; AgentGuard turns them into executable, validated world scenarios.

## Where AgentGuard is behind

- **Scale of the security suite.** AgentDojo (629 cases) and InjecAgent (1,054) are far larger than AgentGuard's handful of injection scenarios. AgentGuard could run their attacks as scenarios in a future version.
- **Injection detection.** AgentShield uses explainable regex heuristics. Trained classifiers (Prompt Guard, Lakera) will catch more paraphrased attacks. AgentShield is designed so that policy, not detection, is the last line of defence.
- **User simulation.** τ-bench simulates a conversational user. AgentGuard tasks are single instructions.
- **Domains.** One domain (customer-support refunds) in the MVP.
