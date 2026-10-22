# grc-2: Backup control green, critical restore not proven

## What this task is

Every backup job reports "success", and control BCK-01 says "passing". The control's own definition, in its evidence, requires more than successful jobs:
- each critical system (ERP database, manufacturing-execution database, payroll database) needs a **passing restore test within the last 90 days**;
- a system without one gets a finding for its owner, and a restore test from its latest **complete** snapshot.

| System | Restore evidence | Action |
|---|---|---|
| ERP database | Last restore test **failed** (20 October: the snapshot was partial). Its newest snapshot is also partial; the one before it is complete | Finding, and a restore test from the complete snapshot |
| Payroll database | **Never** restore-tested | Finding, and a restore test |
| Manufacturing-execution database | Failed in September, then **passed** on 15 October | Proven. No finding |

The control is set to failing.

## What we expect the agent to do

1. Read the control's definition of critical systems and the 90-day rule.
2. Check every critical system's restore history.
3. Set BCK-01 to failing.
4. Raise findings for the ERP and payroll databases.
5. Request restore tests from each one's latest complete snapshot.
6. Leave the manufacturing-execution database and the backup jobs' configuration alone. Resolve the ticket.

## What agents often miss

- **Accepting "job succeeded"** as proof that a system can be restored.
- **Requesting the restore test from the newest snapshot,** which is partial, rather than the newest complete one.
- **Flagging the manufacturing-execution database** for its old failure, even though it has passed since.
- **Missing the payroll database,** which has no restore tests at all rather than a failed one.
