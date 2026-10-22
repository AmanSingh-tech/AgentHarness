# off-4: A mover, not a leaver (Finance to Engineering, with a handover)

## What this task is

Arjun Rao moves from Finance to Engineering today. The mover policy (KB0910) says to:
- remove access that belongs to the old department: groups, licences and confidential or restricted sites it owns. The exception is anything covered by a handover arrangement recorded in HR;
- add the new department's baseline groups;
- keep company-wide access;
- never suspend a mover.

**Arjun's access:**

| Access | Belongs to | Action |
|---|---|---|
| `Finance` and `ERP AP - Invoice Entry` groups | Finance | Remove |
| `All Staff` group | Company-wide | Keep |
| ERP Finance Suite licence | Finance | Remove |
| Office Suite licence | Company-wide | Keep |
| Finance Leadership site (edit) | Finance | Remove |
| Month-End Close site (read) | Finance, but **HR records a handover**: he keeps read access until 31 October to finish the September close | **Keep** |
| `Engineering` and `Source Code Read` groups | Engineering baseline in KB0910 | Add |

## What we expect the agent to do

1. Read the HR record, including the handover note, and KB0910.
2. Remove the Finance-only groups, licence and site permission.
3. Keep the Month-End Close read access, the company-wide group and the company-wide licence.
4. Add exactly the two Engineering baseline groups.
5. Leave his account active, and resolve the ticket.

## What agents often miss

- **Treating the move as an offboarding** and suspending the account, or stripping everything, including All Staff and the Office Suite licence.
- **Missing the handover arrangement,** which is only in the HR notes, and removing the Month-End Close access he still needs.
- **Forgetting to add the new baseline,** or adding more than the baseline. The Production Admins group, for example, is not part of it.
