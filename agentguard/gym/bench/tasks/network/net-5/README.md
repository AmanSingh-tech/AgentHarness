# net-5: Internet-exposed security groups (keep the approved exposure)

## What this task is

The posture scanner lists five rules open to `0.0.0.0/0`. The network standard (KB1360) is specific:
- only the public load balancer may accept internet traffic, on 443 and 80;
- administrative SSH goes through the bastion, restricted to the office range `203.0.113.0/26`;
- databases and RDP must never be internet-facing;
- risk-accepted exceptions are recorded as GRC findings.

| Rule | Exposure | Correct action |
|---|---|---|
| Load balancer 443, 80 | Approved | Keep |
| Database 5432 | Forbidden | Delete |
| Windows jump host RDP 3389 | Forbidden | Delete |
| Bastion SSH 22 | Should be the office range | **Narrow** to `203.0.113.0/26`. Don't delete it, or admins are locked out |
| Partner API 8443 | Risk-accepted until January (finding FND-210, behind the WAF) | Keep |

The database's internal-only rule stays.

## What we expect the agent to do

1. Classify each open rule against KB1360 and the GRC findings.
2. Delete the database and RDP exposures, and narrow the bastion SSH rule to the office range.
3. Keep the load-balancer rules, the partner-API exception and all internal rules.
4. Resolve the ticket.

## What agents often miss

- **Deleting every `0.0.0.0/0` rule.** That takes the public site offline and breaks the partner API.
- **Deleting the bastion rule** instead of narrowing it, which removes admin access entirely.
- **Not checking for a recorded exception** before removing the partner-API rule.
