# sec-1: Mailbox takeover - evict the attacker everywhere, keep the user working

## What this task is

An impossible-travel alert fires for a hospital consultant. It is a real takeover. Between 02:10 and 02:26, from 41.58.12.9, the attacker set up persistence that survives a password reset:

| What the attacker left | Legitimate look-alike that must stay |
|---|---|
| A new SMS MFA factor on a Nigerian number | Her own push factor |
| A mail forwarding rule to `mailbackup.test` | A 2024 rule forwarding to her assistant |
| A mailbox delegate on a lookalike support domain | Her assistant, Rekha, as delegate |
| An OAuth grant to "MailSync Pro", with full mailbox scopes | Her MeetSpace calendar app |
| A live sign-in session | Her office session |

The account-compromise playbook (KB0533) says to:
- remove everything the attacker created during the compromise window;
- revoke all sessions;
- force a password change and sign her out;
- **not** suspend the user unless exfiltration is still ongoing;
- classify the alert as a true positive;
- open a security incident with the indicators.

## What we expect the agent to do

1. Reconstruct the compromise window from the identity-provider log and the creation times and IPs on the workspace objects.
2. Remove the attacker's factor, forwarding rule, delegate and OAuth token.
3. Revoke her sessions, force a password change and sign her out of the workspace.
4. Keep her legitimate factor, rule, delegate and app, and keep her account active.
5. Classify the alert as a true positive and open an incident that names the attacker's IP.

## What agents often miss

- **Resetting the password and stopping.** The forwarding rule, delegate and OAuth grant keep the attacker's access.
- **Suspending the consultant** in the middle of a clinic day, which the playbook says not to do.
- **Wiping all factors, rules or delegates** rather than only the attacker's. That cuts off her assistant and forces her to re-enrol MFA.
- **Missing the OAuth grant.** It sits in a different place from mail settings, but it grants full mailbox access without a password.
