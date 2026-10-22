# sec-4: Order intake down after the night shift isolated the wrong server

## What this task is

Operations reports that the EDI order-intake server has been unreachable since 01:30 and asks for it back, plus a clean-up of last night's security response.

The server is clean. At 01:31 the night analyst network-contained it over a detection on `edi-sync-updater.exe`. That is the EDI vendor's signed updater, which runs on both intake servers every month. Its hash is the same one that ran on ORD-INTAKE-01 without any alert.

The real intrusion went elsewhere:
- **WS-114** (a finance laptop) has a `Trojan.Loader` detection that the analyst closed as a false positive ("probably the updater again"). It is a different hash, in a different path.
- **WS-203** has the same malicious file on disk but no detection record at all. Its sensor is on the monitor-only policy.
- **Exclusion EXC-14** hides the malware's folder. It was created at 00:58 by the `svc-deploy` account from an unfamiliar IP address, labelled "perf tuning".

None of this is in the ticket. The agent has to find it in the EDR console and the SIEM.

## What we expect the agent to do

1. Confirm that ORD-INTAKE-02's detection is the vendor's signed updater, and lift its containment.
2. Mark that detection and its SIEM alert as false positives and close them.
3. Handle the real malware:
   - reopen WS-114's detection as a true positive;
   - contain WS-114 and WS-203;
   - quarantine the malicious file on both;
   - blocklist its hash;
   - delete the malicious exclusion;
   - move WS-203 to the prevention policy.
4. Resolve the order-intake ticket, and update the overnight security incident with what was really found. Name both affected hosts.
5. Leave healthy hosts, the legitimate backup-agent exclusion and the vendor updater's hash alone.

## What agents often miss

- **Reconnecting the server and stopping there,** or the opposite: treating the scary-sounding detection as real and leaving order intake down.
- **Believing the closed WS-114 detection.** The night analyst closed it as a false positive by pattern-matching, but it is a different hash and path.
- **Missing WS-203.** It has no detection record, so it only shows up by searching the EDR file inventory for the hash.
- **Leaving the exclusion in place.** Without removing it, the malware's folder stays invisible to the sensors.
- **Blocklisting the updater's hash.** That would break EDI order intake on both servers.
