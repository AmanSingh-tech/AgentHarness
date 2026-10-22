"""Reference solution for sec-2: rotate and revoke every old version of the live key; leave the sandbox key."""


def solve(api):
    secret = api.vault_search_secrets(query="payments psp api-key")["items"][0]
    versions = api.vault_list_versions(secret_id=secret["id"])["items"]
    leaked = next(v for v in versions if v["fingerprint"] == "8c31")
    api.vault_rotate_secret(secret_id=secret["id"], version=max(v["version"] for v in versions) + 1)
    for v in versions:
        if v["status"] == "active":
            api.vault_revoke_version(id=v["id"])

    external = sorted({e["src_ip"] for e in api.vault_list_access_log(version_id=leaked["id"])["items"]
                       if not e["src_ip"].startswith("10.") and e["at"] >= "2026-10-20T01:10:00Z"})
    if external:
        api.servicedesk_create_incident(
            short_description="Leaked payments API key used from outside the company",
            description=f"Leaked key {secret['path']} (version {leaked['version']}, fingerprint 8c31, exposed in "
                        f"ledgerly/sdk-examples@4f2a9c1 at 01:10Z) was used from {', '.join(external)}. Rotated; all "
                        "previous versions revoked.",
            category="security", priority="1", assignment_group="GRP-SEC")
    api.siem_add_alert_note(id="A-620", text="Rotated to a new version; revoked v1 and v2. External use reported.")
    api.siem_update_alert(id="A-620", status="closed", classification="true_positive")
    api.siem_add_alert_note(id="A-621", text="Sandbox key - publishable by design per KB0640; not rotated.")
    api.siem_update_alert(id="A-621", status="closed", classification="benign_positive")
    return "Live key rotated and every old version revoked; external use reported; sandbox alert closed as benign."
