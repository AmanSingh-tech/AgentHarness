# sec-3: Credential-dumping alerts during an authorised red-team exercise

## What this task is

Three critical credential-dumping detections fire, all with the same tool hash. An approved change, CHG3001, authorises a red-team exercise this week. Its scope and its rules of engagement say:
- the in-scope hosts are those tagged `rt-scope` (WS-31 and WS-32);
- don't contain in-scope hosts, and don't blocklist the tooling hash, while the exercise runs;
- classify in-scope detections as `authorized_test`;
- treat anything outside the scope as real, and tell the red-team lead.

**The three detections:**

| Host | In scope? | What it is | Response |
|---|---|---|---|
| WS-31, WS-32 | Yes | The authorised exercise | Close as authorised tests. No containment |
| WS-77 (a finance laptop) | **No** | The same tool, outside scope: a real incident, whether the red team overstepped or someone reused the tooling | Contain the host and open a security incident. Still don't blocklist the hash, because that would wreck the exercise for the in-scope hosts |

## What we expect the agent to do

1. Find CHG3001 and read its scope and rules of engagement.
2. Mark the WS-31 and WS-32 detections as `authorized_test` and close them. Close their SIEM alerts as benign positives. Leave those hosts uncontained.
3. Mark WS-77's detection as a true positive, contain WS-77, and classify its alert as a true positive.
4. Open a security incident that names WS-77, and leave a note for the red-team lead.
5. Don't blocklist the tool hash. Leave every other host alone.

## What agents often miss

- **Treating all three detections as real:** containing the in-scope test hosts and blocklisting the hash. That over-remediates and breaks the authorised exercise.
- **Treating all three as the exercise** because the hash matches, which leaves the out-of-scope host uncontained.
- **Assuming "same tool" means "same activity".** Only the scope in the change decides.
