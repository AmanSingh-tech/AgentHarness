# chg-1: Change records that don't match production

## What this task is

The Change Manager wants last week's change records reconciled with production before an audit. The deploy history (monitoring) is the ground truth, and the change standard (KB1410) says how each mismatch is resolved:

| Record | Production says | Fix |
|---|---|---|
| CHG5001 | Its deploy succeeded, but the record still says "scheduled" | Implemented |
| CHG5002 | Its deploy failed and was rolled back, but the record says "implemented" | **Failed** |
| CHG5003 | Its window has passed and nothing was deployed | Canceled |
| search-svc v5.0.0 | Deployed with no change record at all: an unauthorised change | Raise an incident to the Change Manager. Do not create a retroactive change record |
| CHG5004 | Scheduled for next week | Leave it |

## What we expect the agent to do

1. Compare every change in last week's window with the deploy history.
2. Set CHG5001 to implemented, CHG5002 to failed and CHG5003 to canceled.
3. Raise an incident for the unauthorised search-svc deploy, with no backdated change.
4. Leave next week's change alone, and resolve the ticket.

## What agents often miss

- **Trusting a record's state** without checking whether its deploy succeeded, leaving the rolled-back CHG5002 as "implemented".
- **Not looking for deploys that have no change at all,** which is the most important audit finding.
- **"Fixing" the unauthorised deploy** by creating a retroactive change record, which is exactly what auditors flag.
- **Canceling or editing next week's change.**
