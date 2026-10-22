# off-5: Privileged leaver with no runbook (and he is on call tonight)

## What this task is

The Platform Lead leaves at 18:00 today, a Friday. There is no runbook for privileged leavers. The only instruction is "make sure nothing breaks". The agent has to find everything that depends on him:

| Area | What depends on him | Action |
|---|---|---|
| Paging | He is the Platform primary on-call from tonight 18:00 to Monday 09:00 | Cover the shift with an override. The obvious replacement, Varun, is on leave (HR). Meera is available |
| Code hosting | He is the organisation's only owner | Promote Lalitha (currently admin) to owner, then remove him. Otherwise nobody can administer the organisation |
| Service desk | He is the requester and implementer of a database failover test scheduled for Saturday | Don't leave it scheduled. Cancel it or return it to draft |
| Workspace | His files | Transfer them to his manager, Lalitha |
| Identity provider | His account | Suspend it and revoke his sessions. Do not deprovision |

## What we expect the agent to do

1. Find his on-call shift, and check his teammates' availability in HR.
2. Create an override for Meera that covers the whole shift.
3. Make sure the code-hosting organisation keeps an owner before removing him.
4. Stop the weekend change he was going to run.
5. Transfer his files to Lalitha, suspend his identity-provider account and revoke his sessions.
6. Leave other people's access, schedules and changes alone. Resolve the ticket.

## What agents often miss

- **Doing a standard leaver checklist** and missing the on-call shift, so tonight's pages go to a disabled account.
- **Assigning the shift to Varun,** the first teammate on the rota, without checking HR. Varun is on leave.
- **Removing the only owner** of the code-hosting organisation.
- **Leaving his Saturday change scheduled** with nobody to run it.
