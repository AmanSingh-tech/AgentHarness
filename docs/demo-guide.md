# Demo guide: AgentGuard at AgentOps 2026

This guide is for the person presenting. It covers what to set up, what to click, what to say, and what to do if something breaks.

The background for judges and answers to likely questions are in [hackathon.md](hackathon.md).

**The one-line pitch:** *Four AI agents run a refund inbox and an IT access queue end to end. Claude makes the decisions, a policy check has to agree, humans approve what matters, and every outcome is checked against the system of record.*

---

## How the demo maps to the judging criteria

| What the judges look for | Where they see it | Minute |
|---|---|---|
| A real domain (Retail and Supply, IT Infrastructure) | RefundOps and AccessOps on the **Business processes** page | 0:00, 3:30 |
| Ingestion → decision → action → outcome reporting | Four agent cards filling with tool calls, then the outcome report | 0:00 |
| Intelligent decision-making | **Decisions: Claude + policy check**: Claude's reasoning on every row | 2:00 |
| Business value | Seven of ten tickets handled with no person; ₹6,000 confirmed in the ledger | 1:30 |
| Responsible-AI controls | The controls panel; the blocked exfiltration; the caught false "success" | 1:30, 4:30, 5:30 |
| Human approval and oversight | The ₹4,500 refund and the payments admin grant wait for your click; a rejection is reported honestly | 0:45, 3:00 |

---

## The day before

1. **Install and build once.** This takes about five minutes.
   ```bash
   cd ~/AgentHarness && git pull
   python3 -m venv .venv && .venv/bin/pip install -e ".[dev,llm,langgraph,mcp,server]"
   source .venv/bin/activate
   cd dashboard && npm install && npm run build && cd ..
   ```
2. **Log in to Claude Code** (`claude`, then `/exit`). Then run one batch with Claude, so you know it works on this laptop:
   ```bash
   agentguard ops run --decider claude --model sonnet
   ```
   You should see "policy check agreed: 9" and the verdict `CORRECT_SUCCESS`. It costs about $0.02.
3. **Run the whole safety net once:**
   ```bash
   pytest -q && agentguard validate-scenarios && agentguard demo
   ```
4. **Make the benchmark charts.** The Benchmark page reads saved reports:
   ```bash
   agentguard benchmark --attempts 3
   ```
5. **Save backups.** Keep the report files in `reports/` (`refundsops-*.md`, `accessops-*.md`), so you have something to show if everything else fails.

## 30 minutes before

```bash
cd ~/AgentHarness && source .venv/bin/activate
agentguard serve                 # leave this terminal open
```

Open these tabs, in this order:

| Tab | URL | Why |
|---|---|---|
| 1. Showcase | `http://127.0.0.1:8000/site/?noloader` | The opening slide, and the replay if the live demo fails |
| 2. Dashboard | `http://127.0.0.1:8000/` | The live demo |
| 3. Terminal | `agentguard ops run` ready to press Enter | Backup, and proof it isn't only a UI |

Before you start:
- Turn on Do Not Disturb.
- Set the browser zoom to 125% so the back row can read it.
- Choose dark theme on the showcase, using the ◐ button in the top right.

---

## The script (seven minutes)

### 0:00 Open (30 seconds), Showcase tab

**Show:** the hero, then scroll to the four process cards.

**Say:** "Companies want agents to do real work, refunds and access requests, but nobody can prove what an agent did or stop it doing the wrong thing. We built multi-agent systems that run two real processes. Every action goes through one guarded gateway, and every outcome is checked against the system of record."

### 0:30 RefundOps, live (1.5 minutes), Dashboard → Business processes

**Do:**
1. Choose **RefundOps**, **Decisions: rules**, with **AgentShield** and **I approve large refunds** ticked.
2. Press **Work today's inbox**.

**Show:**
- The four agent cards counting tool calls, and the live trace labelled with each agent.
- At about 0:45, **Waiting for your decision** appears: the ₹4,500 refund. Read out the reason, then press **Approve**.

**Say:**
- "Each agent has its own identity. Intake and reporting can only read; only the action agent can move money, and only up to its limit."
- "Above ₹2,000, a person approves. That isn't the agent being polite; the gateway holds the call."

**Then show the outcome report:**
- ₹6,000 refunded, both confirmed in the ledger.
- Four refusals, each with its reason.
- T-107 (₹18,000) escalated to finance.
- T-108 escalated to security as an injection.
- The verdict badge reads `CORRECT_SUCCESS`.
- The controls panel shows one approval, one injection detected, two verifications passed, and the audit chain verified.

**Say:** "Seven of ten tickets were handled with no person. People see only the exceptions, and each comes with its reason."

### 2:00 Claude decides (1 minute)

**Do:**
1. Set **Decisions** to **Claude + policy check** and the model to **Sonnet**.
2. Press **Work today's inbox** again, then approve the ₹4,500 refund.

**Show:**
- The **Why** column now begins with Claude's own explanation.
- Each row is labelled "decided by claude:sonnet, policy check agrees".
- The **Decision-making** panel: 9 agreed, 0 disagreed, T-108 withheld from the model, about $0.02.

**Say:**
- "Claude reads each ticket in plain language and decides. We don't trust it blindly: a rule-based check must agree, or a person decides."
- "The injected ticket is never shown to the model."
- "In an early run, Claude escalated a grant our policy allows. The check caught the disagreement and sent it to a person. That's the safeguard working."

### 3:00 Honest failure (30 seconds)

**Do:** run RefundOps once more and press **Reject** on the ₹4,500 refund.

**Show:** T-102 reads "stopped by controls", and the verdict is `CORRECT_FAILURE_REPORTED`.

**Say:** "When a person says no, the system says it didn't finish. It doesn't claim success."

### 3:30 AccessOps (1 minute)

**Do:** choose **AccessOps** and press **Work the access queue**. Approve the payments-platform admin grant (AR-205).

**Show:**
- AR-206 is denied for segregation of duties: the employee already has write access to payments.
- AR-204 is denied because the employee has left the company.
- AR-209 is escalated to security, for an injected justification.
- All three grants are confirmed in the directory.

**Say:** "This is the same gateway in a second domain, IT infrastructure, with the controls an auditor asks for."

### 4:30 Stopping exfiltration (1 minute), Dashboard → Live run

**Do:** choose scenario `secret_exfiltration`, agent `scripted:adversarial`, shield on, and press **Run**. Then open **Blocked actions**.

**Show:** the chain `read_secret → encode → send_email`, blocked at the send. The evidence shows the data was followed through base64.

**Say:** "The agent tried to email a secret after encoding it. We track sensitive data through encodings and split calls, all the way to any external sink."

### 5:30 Catching a lie (1 minute)

**Do:** choose scenario `refund_false_success` with agent `scripted:naive`. Run it with the shield **off**, then with it **on**.

**Show:**
- **Off:** the banner reads "❌ Agent incorrectly reported success". The tool said OK, but the ledger says otherwise.
- **On:** post-action verification catches it before the agent sees the false OK.

**Say:** "Agents believe their tools. We check the system of record after every refund and grant."

### 6:30 Numbers, then a regression test (30 seconds)

**Do:** open **Benchmark** and point at v1 and v2 with the shield off and on. Then go back to the blocked run and press **Promote to regression**.

**Say:**
- "With the shield on: zero duplicate refunds and zero false success claims. A better agent pushes success to 96%."
- "Every incident becomes a test. It's kept only if a do-nothing agent fails it and the reference agent passes it."

**Close:** "Real processes, AI that decides, controls outside the model, and evidence for every claim. Thank you."

---

## If something goes wrong

| Problem | What to do | What to say |
|---|---|---|
| Claude doesn't answer (no internet, logged out) | Nothing. The run continues, and the Decision-making panel says the rules decided | "That's the fallback working: if the model is unavailable, the policy decides, and the report says so." |
| No approval card appears | Make sure **I approve large refunds** is ticked and **AgentShield** is on | |
| Dashboard won't load | Run `cd dashboard && npm run build`, then restart `agentguard serve` | |
| Server won't start: port in use | `agentguard serve --port 8010` | |
| Nothing works | Showcase tab → **Replay run**, then show the saved `reports/*.md` | "This replays a real run recorded with Claude Sonnet." |
| Wi-Fi is down | Everything except the Claude decider is offline. Use **Decisions: rules** | |

## After the demo

People can try it themselves from the showcase's **Run it yourself** section, or from [the README](../README.md).
