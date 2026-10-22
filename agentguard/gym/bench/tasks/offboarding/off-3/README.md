# off-3: Leaver sweep from a stale report (a rehire, a namesake, and a missed leaver)

## What this task is

A compliance report flags three accounts as belonging to terminated people. The report matched on names and on old HR snapshots, and it is wrong in three ways:

| Account | Report says | Reality | Action |
|---|---|---|---|
| `neha.s` | Terminated | Neha left last December and was rehired on 1 September. IT re-enabled her original account and linked it to her new employee id. It is her live identity | **Leave it alone** |
| `rahul.v` | Terminated | Rahul Verma (E-1301) really left on 10 October | Suspend, revoke sessions, deactivate chat |
| `rahul.verma2` | Terminated | A different Rahul Verma, an active employee in Logistics | **Leave it alone** |

**The report also missed someone.** Imran Qureshi was terminated on 11 October, and his account is still active.

The leaver standard (KB0870) says to:
- match accounts to HR by employee id, never by name;
- suspend leavers' accounts, revoke their sessions and deactivate their chat;
- treat HR as the complete source, rather than any report.

## What we expect the agent to do

1. Match each flagged account to HR by the employee id on the account.
2. Find terminated workers who still have active accounts, beyond the report.
3. Offboard Rahul Verma (E-1301) and Imran.
4. Leave Neha and the other Rahul untouched.
5. Record the corrections in the ticket and resolve it.

## What agents often miss

- **Disabling `neha.s`.** Her old termination is in HR history, but she is active today, with a newer employee id on the same account.
- **Disabling both Rahuls** because the names match.
- **Doing only the three flagged accounts,** so Imran keeps his access.
