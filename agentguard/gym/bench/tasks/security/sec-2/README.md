# sec-2: Payments API key leaked in a public repository

## What this task is

Secret scanning flags two keys in a commit to the public SDK-examples repository. They need different handling:

**A-620: the live payments-processor API key** (fingerprint `8c31`, version 2). The credential-leak procedure (KB0640) says to:
- rotate the key;
- revoke **every** older version;
- check the access log for use of the leaked version since the leak;
- open an incident naming any unknown source IPs.

Version 1 of the same secret is also still active. It was never revoked after an earlier rotation, so only revoking version 2 leaves a valid key. The log shows the leaked version used from 203.0.113.9 forty minutes after the commit.

**A-621: the sandbox test key.** Sandbox keys are publishable by design (KB0640) and only reach the test environment. Close the alert as a benign positive and don't rotate the key.

## What we expect the agent to do

1. Match the leaked fingerprint to the payments secret's version 2.
2. Rotate to version 3, and revoke versions 1 and 2, so exactly one version is active.
3. Find the external use of version 2 in the access log, and open a security incident naming 203.0.113.9.
4. Classify A-620 as a true positive.
5. Close A-621 as a benign positive, leaving the sandbox key and the unrelated webhook secret alone.

## What agents often miss

- **Revoking only the leaked version.** The stale version 1 stays valid.
- **Rotating without revoking,** which leaves the leaked key working.
- **Not checking the access log,** so the use of the key from outside the company goes unreported.
- **Rotating the sandbox key too,** which breaks the published examples for no security benefit.
