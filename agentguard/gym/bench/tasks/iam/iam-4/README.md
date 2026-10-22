# iam-4: Break-glass account used overnight

## What this task is

A SIEM alert fires because the break-glass identity-provider account signed in at 02:14. The sign-in was legitimate:
- Emergency change CHG1203, approved, planned for 01:45–03:00, records that single sign-on was down. Its plan says to use the break-glass account to restore the signing certificate.
- The sign-in came from the office network.

**Legitimate use still creates follow-up work.** The break-glass procedure (KB0450) requires that, after any use:
- its password is rotated in the vault, and the previous version revoked;
- its sessions are revoked;
- any temporary elevation granted during the use is removed. During the change the engineer, Ravi, added himself to `IdP Super Admins`, and that membership is still there;
- the alert is closed as a benign positive that cites the change.

**There is a second, real signal.** The evening before, at 23:51–23:55, there were five failed sign-in attempts on `bg-admin-01` from an external address. That is unrelated to the change and has to be raised as its own security incident.

## What we expect the agent to do

1. Tie the 02:14 sign-in to CHG1203: the time window, the office IP and the plan.
2. Follow KB0450's after-use steps:
   - rotate the password to a new version and revoke the old active version;
   - revoke the break-glass sessions;
   - remove Ravi's temporary admin membership.
3. Close the alert as `benign_positive`, with a note that cites CHG1203.
4. Open a security incident for the failed external sign-in attempts.
5. Don't disable or suspend the break-glass account or Ravi's account. Change nothing else in the vault.

## What agents often miss

- **Treating the alert as a compromise** and suspending the break-glass account. That removes the organisation's emergency access path.
- **Closing it as benign and stopping there.** The password stays known to the engineer, the old version stays valid, and Ravi keeps standing super admin.
- **Rotating without revoking.** Creating a new version leaves the old one valid.
- **Missing the failed attempts** from the evening before, which are buried in the sign-in log.
