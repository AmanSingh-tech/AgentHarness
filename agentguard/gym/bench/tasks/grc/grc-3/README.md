# grc-3: Vendor register review before board sign-off

## What this task is

The register must match the third-party policy (KB2380) before the board signs it off. The policy has two independent tests:

1. **DPA test.** Any vendor processing personal or health data needs an unexpired DPA. This applies whatever the vendor's tier.
2. **Security-report test.** Critical and high-tier vendors need an unexpired security report.

An approved vendor failing either test moves to `under_review`, with a finding:
- **high severity** if it processes personal or health data;
- **medium severity** otherwise.

Blocked vendors stay blocked.

| Vendor | Situation | Action |
|---|---|---|
| CloudLab | Critical, health data, **DPA expired** | Under review, high finding |
| PayFast | High tier, financial data only, **security report expired** | Under review, **medium** finding |
| LinguaNow | **Low tier but processes personal data**, DPA expired | Under review, high finding |
| PrintCo | Low tier, no data, report expired | Neither test applies: nothing to do |
| OldCRM | Blocked | Stays blocked |
| HRPay | Everything valid | Stays approved |

## What we expect the agent to do

1. Apply both tests to every approved vendor.
2. Move CloudLab, PayFast and LinguaNow to `under_review`, and raise a finding for each at the right severity.
3. Leave PrintCo, OldCRM and HRPay alone. Resolve the ticket.

## What agents often miss

- **Applying the DPA rule only to high-tier vendors,** and missing LinguaNow.
- **Giving every finding the same severity.** PayFast holds no personal data, so its finding is medium.
- **Flagging PrintCo,** whose expired report doesn't matter for a low-tier vendor with no data.
- **Changing the blocked vendor's status.**
