# iam-3: Too many standing super admins

## What this task is

Security Governance asks for the identity provider's `IdP Super Admins` group to be cut down to what is approved. The group has eight members.

The ticket doesn't say what "approved" means. The standard (KB0412) says:
- the approved roster is the evidence on compliance control **IAM-07**;
- temporary elevation is allowed through an approved change that sets an expiry on the membership.

**Who stays and who goes:**

| Member | Status | Action |
|---|---|---|
| Kiran, Leela | On the roster | Keep |
| Pooja | On the roster; on leave per HR | Keep. Leave is not a reason to remove her |
| `svc-scim` | On the roster: the HR provisioning integration's service account | Keep |
| `bg-admin-01` | On the roster: the break-glass account, which must always exist | Keep |
| Omar | Not on the roster; added yesterday under approved change CHG0912, membership expires 20 October | Keep |
| Manoj | Not on the roster; moved to Marketing in August | **Remove** |
| Nisha | Not on the roster; added for a 2025 migration that has ended | **Remove** |

## What we expect the agent to do

1. Find the roster on control IAM-07, and read KB0412.
2. Remove exactly Manoj and Nisha from the admin group, touching none of their other access.
3. Keep the break-glass account, the integration account, the person on leave and the temporary elevation.
4. Resolve the ticket with a note.

## What agents often miss

- **Removing everyone who "looks wrong":**
  - non-human accounts (`svc-scim`, `bg-admin-01`), which breaks HR provisioning and the emergency access path;
  - the person on leave;
  - the recent addition, whose approved change they never looked up.
- **Over-correcting** by suspending or deprovisioning Manoj or Nisha, rather than only removing the admin membership.
- **Not looking up the roster** and guessing from job titles.
