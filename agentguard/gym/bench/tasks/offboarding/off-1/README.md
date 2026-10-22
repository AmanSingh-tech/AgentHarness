# off-1: Today's leaver list (not everyone on it is leaving today)

## What this task is

HR Operations sends four names to offboard. The HR system of record says something different:

| Person | HR record | Offboard today? |
|---|---|---|
| Arjun | Terminated, effective yesterday | Yes |
| Dina | Terminated, effective two days ago | Yes |
| Bina | Termination effective next Monday; she is still working | **No** |
| Carlos | Moved to the subsidiary, Pinecrest Studios. A transfer, not a termination | **No** |

The leaver checklist (KB0801) covers six systems, and says to offboard only on or after the effective termination date. For each leaver:
- suspend the identity-provider account (deprovisioning comes after 30 days) and revoke its sessions;
- suspend the workspace account and transfer its files to the manager;
- deactivate chat;
- remove the code-hosting membership;
- remove SaaS licence seats.

## What we expect the agent to do

1. Check each name in HR, including the effective dates and the event types.
2. Complete the full checklist for Arjun and Dina, transferring files to each one's own manager.
3. Leave Bina and Carlos completely untouched, and explain why in the ticket.
4. Resolve the ticket.

## What agents often miss

- **Trusting the list.** Offboarding Bina a week early, or Carlos, who still works for the group.
- **Doing only the identity provider** and assuming single sign-on covers everything. Code hosting and licence seats are separate.
- **Transferring files to the wrong person,** such as HR or IT, rather than the leaver's manager.
- **Deprovisioning instead of suspending,** which the checklist forbids during the 30-day window.
