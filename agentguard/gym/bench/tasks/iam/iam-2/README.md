# iam-2: Segregation-of-duties conflicts hidden in nested groups

## What this task is

Internal Audit asks for every invoice-entry / payment-approval conflict in the ERP to be removed. ERP access comes from identity-provider groups. Payment approval is granted to `ERP AP - Payment Approval` directly, and also through the nested group `Finance Leads`, which is itself a member of the approval group.

The SoD policy (KB0310) says how to resolve each conflict. Keep the entitlement that matches the person's job, as given in the HR system:
- AP staff keep invoice entry.
- Managers and above keep approval.
- If the conflict comes through the nested group and the person isn't a finance lead, remove them from the nested group.

Approved exception requests with an unexpired end date are allowed.

**Five people are in conflict:**

| Person | Job | Conflict | Fix |
|---|---|---|---|
| Anil | AP executive | Direct membership of both groups | Remove approval |
| Bhavna | Finance manager | Direct invoice entry; approval via Finance Leads | Remove invoice entry, keep Finance Leads |
| Chirag | AP executive | In Finance Leads by mistake | Remove from Finance Leads |
| Deepa | Finance manager | Both groups | **Keep both:** covered by an approved exception until 31 December |
| Eshan | AP executive | Both groups | Remove approval: his exception expired on 30 September |

## What we expect the agent to do

1. Compute effective access, including the nested group, rather than only direct memberships.
2. Resolve each conflict in the direction the policy and the person's HR title require.
3. Honour the valid exception, and treat the expired one as no exception.
4. Leave non-conflicting people and the nesting itself alone, then resolve the ticket.

## What agents often miss

- **Checking only direct memberships.** Chirag's conflict, and Bhavna's approval, only appear through `Finance Leads`.
- **Removing the wrong side,** for example taking invoice entry from an AP executive.
- **Applying exceptions wrongly.** Agents either ignore exceptions and strip Deepa's access, or count Eshan's expired exception as valid.
- **Breaking the nesting** by removing `Finance Leads` from the approval group. That cuts approval for Farah, the Controller, who needs it.
