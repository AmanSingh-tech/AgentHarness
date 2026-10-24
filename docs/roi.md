# What AgentGuard is worth: the ROI model

The website's calculator (the **ROI** section) uses the formula on this page. Three inputs are measured from runs in this repo. The rest are assumptions you replace with your own numbers.

## Measured

| Figure | Value | Where it comes from |
|---|---|---|
| Cases resolved with no person | **70%** | `agentguard ops run` and `agentguard ops run --process access`. Each processes 10 cases: 2 are escalated to a person and 1 waits for a human approval, so 7 finish with no one involved. |
| Model cost per case | **₹0.17** | `--decider claude --model sonnet` makes one batched call per 10 cases, about $0.02 (₹0.17 per case at ₹84/$). With the rule-based decider, the cost is zero. |
| Costly mistakes with AgentShield on | **0** | `agentguard benchmark --attempts 3`, 75 runs per configuration: 0 duplicate refunds and 0 false success claims with the shield on, against 3 and 3 with it off. |

## Assumptions (yours)

| Input | Default | Meaning |
|---|---|---|
| Cases per month | 4,400 | 200 a day over 22 working days |
| Minutes per case, by hand | 8 | Reading the ticket, looking up the order or employee, checking the rules, acting, replying |
| Loaded cost per hour | ₹500 | Salary plus overheads for an operations analyst |
| Costly mistakes per 100 cases | 1 | Duplicate payments, over-limit refunds, wrong grants, a "done" that wasn't |
| Cost of one mistake | ₹3,000 | The money lost plus the time spent putting it right |

## Formula

```
automated        = cases × 70%
hours saved      = automated × minutes ÷ 60
cost per case, by hand       = minutes ÷ 60 × hourly cost
cost per case, with agents   = 30% × cost per case by hand + ₹0.17
losses avoided   = automated × mistakes per 100 ÷ 100 × cost of one mistake
net value        = hours saved × hourly cost + losses avoided − cases × ₹0.17
```

## Worked example (the defaults)

| Step | Value |
|---|---|
| Automated cases | 4,400 × 0.7 = **3,080** |
| Hours saved | 3,080 × 8 ÷ 60 = **411 hours** (about 2.5 full-time analysts) |
| Labour value | 410.7 × ₹500 = ₹2,05,333 |
| Cost per case, by hand | 8 ÷ 60 × ₹500 = **₹67** |
| Cost per case, with agents | 0.3 × ₹66.67 + ₹0.17 = **₹20** |
| Losses avoided | 3,080 × 1% × ₹3,000 = **₹92,400** |
| Model cost | 4,400 × ₹0.17 = ₹748 |
| **Net value per month** | ₹2,05,333 + ₹92,400 − ₹748 = **₹2,96,985** |

## What the model leaves out

- **Losses avoided assumes the shield stops the same kinds of mistakes in your process.** It stopped duplicates, over-limit actions and false success claims in testing. Mistakes outside the policy are not covered.
- **The 30% that goes to people is still manual.** Escalations should be the hard cases, so they may take longer than the average.
- **Running costs are left out:** hosting, someone to own the policy, and the time to write a tool adapter for a new system. Building the adapter takes a few hours for a REST API (one YAML file, see `examples/payments_backend.yaml`) or a short Python class (`examples/protect_your_tools.py`).
- **The 70% is from two demo processes of 10 cases each.** Measure your own rate by running your queue through `agentguard ops run`-style processes before relying on it.
