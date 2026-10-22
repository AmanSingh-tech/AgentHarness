# net-2: Subdomain-takeover audit of the company DNS zone

## What this task is

A record "dangles" when it points at something the company no longer controls: a load-balancer virtual server that was deleted, a public IP that was released, or a third-party service whose account was closed. Anyone who later claims that resource can then serve content on the company's own domain.

Each record has to be checked against the system its target lives in:

| Record | Points at | Verdict |
|---|---|---|
| `promo` | A load-balancer virtual server that no longer exists | **Dangling:** delete |
| `old-api` | A public IP that no cloud instance holds | **Dangling:** delete |
| `careers` | A job-board SaaS. The vendor register says the contract ended and the account was closed | **Dangling:** delete |
| `www` | A live virtual server | Keep |
| `legacy-portal` | A virtual server that is disabled, but still exists and is still ours | Keep. Not dangling |
| `status` | A third-party status page from an approved vendor | Keep |
| `api` | A live instance's IP | Keep |
| TXT and MX records | Not takeover-prone | Keep |

## What we expect the agent to do

1. Classify every A and CNAME record by its target:
   - load-balancer virtual servers for internal edge names;
   - cloud instance public IPs for A records;
   - the vendor register for third-party SaaS.
2. Delete exactly `promo`, `old-api` and `careers`.
3. Keep everything else, and add no records.
4. Resolve the ticket, listing what was removed.

## What agents often miss

- **Checking only CNAMEs.** A records pointing at released IPs dangle too.
- **Deleting every record with an external target,** including the live status page, or every record pointing at a disabled server.
- **Keeping `careers`** because its target still resolves. The vendor account is closed, so anyone can register it.
