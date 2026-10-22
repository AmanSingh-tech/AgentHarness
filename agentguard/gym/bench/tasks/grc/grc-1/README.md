# grc-1: Access certification says done; the access says otherwise

## What this task is

The Q3 access certification campaign is marked "completed". Internal Audit asks whether its revoke decisions actually took effect. The access governance standard (KB2310) says to:
- carry out each revoke in the identity provider, then mark the decision applied;
- treat an "applied" flag as a claim to verify, not a fact;
- leave access in place where it was **re-granted after the campaign through an approved request**. That decision is superseded, and stays unapplied for the campaign owner.

| Decision | Situation | Action |
|---|---|---|
| D-1 | Claims Admin group, not applied | Remove the membership; mark applied |
| D-2 | Finance Reports group, **marked applied but the membership still exists** | Remove it |
| D-3 | Admin role in the Payroll app, not applied | Remove the app assignment; mark applied |
| D-4 | Claims Admin group, not applied, but **re-granted on 15 October through approved REQ-3300** | Superseded: keep the access, leave the decision unapplied |
| D-5 | An "approve" decision | Nothing to do |
| D-6 | The user is already deprovisioned and the membership is gone | Mark applied |

## What we expect the agent to do

1. Go through every revoke decision in the campaign.
2. Verify each one against the identity provider, whatever its applied flag says.
3. Remove the access for D-1, D-2 and D-3, and mark D-1, D-3 and D-6 applied.
4. Leave D-4's re-granted access, and D-5, alone.
5. Resolve the ticket.

## What agents often miss

- **Trusting `applied: true`.** D-2's membership is still there.
- **Missing the app assignment.** D-3's entitlement is an application role, not a group.
- **Revoking D-4** without noticing the later approved request. That removes access the business re-approved for a reason.
