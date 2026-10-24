# Demo guide: AgentGuard at AgentOps 2026

This guide is for the person presenting. It covers what to set up, what to click, what to say, and what to do if something breaks.

The background for judges and answers to likely questions are in [hackathon.md](hackathon.md). The evidence for each judging criterion is in [judging.md](judging.md).

**The one-line pitch:** *Four AI agents run a refund inbox and an IT access queue end to end. Claude makes the decisions, a policy check has to agree, humans approve what matters, and every outcome is checked against the system of record.*

---

## How the demo maps to the judging criteria

| Criterion | What proves it in the demo | Minute |
|---|---|---|
| **ROI / business value** | Seven of ten tickets handled with no person; ₹6,000 confirmed in the ledger; about $0.02 per batch with Claude; the site's ROI calculator | 1:30, 2:00, 6:45 |
| **Governance and responsibility** | The held ₹4,500 refund, the honest rejection, Claude checked by rules, the blocked exfiltration, the caught false "success", the **evidence report** download | 0:45, 1:45, 2:00, 3:00, 4:30, 5:30 |
| **Reusability** | The same gateway in a second domain (AccessOps); the site's **Integrate** section; `examples/protect_your_tools.py` | 3:30, 6:45 |
| **MVP readiness** | Everything runs live from one command; the public link replays real runs; 293 tests | throughout, 6:45 |
| **Originality** | Claim-versus-outcome grading, faults after the side effect, data followed through encodings, incidents turned into validated tests | 5:30, 6:30 |

## The 60-second public-link tour (for judges who only open the URL)

The link: [https://agent-harness-163s.vercel.app](https://agent-harness-163s.vercel.app) (dashboard at [https://agent-harness-163s.vercel.app/app/](https://agent-harness-163s.vercel.app/app/)).

1. **Site, top to bottom (20 s):** the replayed run, then **Use cases**, **ROI** (change the inputs), **Trust** (hash chain, approvals, framework table) and **Integrate**.
2. **Open the dashboard → Business processes (30 s):** press **Work today's inbox**, then **Approve** the ₹4,500 refund. The outcome report and controls appear. Press **Download evidence report**.
3. **GuardBench (10 s):** the leaderboard, then any task's trap and hidden checks.

The dashboard on the public link replays recorded real runs, so it needs no server and no API key.

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
- Press **Download evidence report** and open it: every agent, the approval with who and when, the injection, both ledger checks, the claim against the verdict, and the hash-chain result.

**Say:**
- "Seven of ten tickets were handled with no person. People see only the exceptions, and each comes with its reason."
- "And this is what we'd hand an auditor: one file per run, built from the hash-chained log." *(Governance)*

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

### Attack playground (2 minutes), Dashboard → Attack playground

This is the part where nothing is pre-run: you, or a judge, type the attack.

**Do:**
1. Choose **Obedient test agent** and untick **AgentShield**. Click **Leak a secret, disguised**.
   The result is red: **Harm happened**, the API key was emailed out.
2. Tick **AgentShield** (a fresh conversation starts) and click the same attack.
   The result is yellow: **Attempted, stopped by AgentShield**, with the chain read_secret → encode → send_email.
3. Choose **Claude (real, through Claude Code)** and let a judge type any attack, or click **Instruction hidden in a ticket**.
   Each message takes 10 to 20 seconds and a fraction of a cent.

**Say:**
- "The obedient agent stands in for a weaker, misconfigured or jailbroken model: it does what it's told."
- "Without the shield, the key leaves the company. With it, we follow the data through the encoding and stop the send."
- "Real Claude refuses most of these on its own, which is good. AgentShield is the guarantee for the day a model is fooled."

**Reading the result:**
- 🟥 **Harm happened:** money above the limit or paid twice, a secret or data sent out.
- 🟨 **Stopped by AgentShield:** the rule and reason are shown.
- 🟩 **The agent didn't do it:** it declined on its own.
- ⬜ **Normal work.**

**What changed** lists refunds, emails, queries and secrets read. **Download evidence report** works for every message.

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

**If you have an extra minute:** open **GuardBench**, pick `ret-3`, reveal the design note, and run Claude Code · Haiku on it live. It takes about 20 seconds and a fraction of a cent.

**Say:** "We also measure agents. GuardBench has 34 enterprise tickets, each with a trap. Sonnet solves 59% and Haiku 38%. With AgentShield on, Sonnet loses one task and costs 31% less."

### 6:45 Value and reuse (15 seconds), Showcase tab

**Show:** the **ROI** section with the default numbers, then **Integrate**.

**Say:** "At 200 cases a day that's about 400 analyst hours a month. And it isn't tied to refunds: any agent, any tools, one YAML policy." *(ROI, reusability)*

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
