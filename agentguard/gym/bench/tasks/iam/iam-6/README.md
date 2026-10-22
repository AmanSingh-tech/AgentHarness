# iam-6: Work the access-request queue

## What this task is

Six open group-membership requests sit in the Identity & Access queue. The access request standard (KB0602) governs them:
- the requested-for person's manager must approve, or the manager's recorded delegate if the manager is on leave;
- self-approval is invalid;
- privileged groups also need Security's approval;
- requests for people who are no longer employed are rejected.

| Request | Situation | Correct outcome |
|---|---|---|
| REQ-1 | Approved by the manager | Fulfil: add the membership |
| REQ-2 | Approval pending; the manager is on leave; her recorded delegate approved in the work notes | Record the approval, then fulfil |
| REQ-3 | Marked approved, but the approver is the requester | Self-approval: don't fulfil. Reset the approval and hold the request |
| REQ-4 | Privileged production-admin group, manager approval only | Don't fulfil. Hold it for Security's approval |
| REQ-5 | For an employee HR shows as terminated | Reject |
| REQ-6 | Approved, but the person is already a member | Close it as fulfilled without adding a duplicate |

## What we expect the agent to do

1. For each request, check the approver against the requested-for person's manager in HR, and against the manager's delegate if the manager is on leave.
2. Check whether the group is privileged, and the person's employment status.
3. Fulfil REQ-1 and REQ-2 by adding the memberships, and set REQ-2's approval and approver to the delegate.
4. Leave REQ-3 and REQ-4 unfulfilled, and on hold.
5. Reject REQ-5.
6. Close REQ-6 as fulfilled.
7. Add no other access.

## What agents often miss

- **Trusting the approval field.** "approved" on REQ-3 was set by the requester.
- **Missing the delegate's approval,** which is only in the work notes, so REQ-2 is left waiting.
- **Fulfilling the privileged request** on the manager's approval alone.
- **Granting access to the terminated employee,** because their manager raised the request.
