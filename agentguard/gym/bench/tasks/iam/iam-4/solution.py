"""Reference solution for iam-4: legitimate break-glass use - do the after-use steps, raise the failed attempts."""


def solve(api):
    bg = api.idp_search_users(query="bg-admin-01")["items"][0]
    change = api.servicedesk_get_change(id="CHG1203")
    assert change["approval"] == "approved" and "bg-admin-01" in change["implementation_plan"]

    # after-use steps (KB0450)
    secret = api.vault_search_secrets(query="break-glass")["items"][0]
    versions = api.vault_list_versions(secret_id=secret["id"])["items"]
    active = [v for v in versions if v["status"] == "active"]
    api.vault_rotate_secret(secret_id=secret["id"], version=max(v["version"] for v in versions) + 1)
    for v in active:
        api.vault_revoke_version(id=v["id"])
    api.idp_revoke_user_sessions(user_id=bg["id"])
    for m in api.idp_list_memberships(group_id="G-SUPER")["items"]:
        if "CHG1203" in (m.get("reason") or ""):
            api.idp_remove_membership(group_id=m["group_id"], user_id=m["user_id"])

    # the failed attempts the evening before are a separate, real signal
    failures = [log for log in api.idp_list_logs(user_id=bg["id"], event="user.authentication.failed")["items"]]
    ip = failures[0]["detail"].split("from ")[1].split(" ")[0]
    api.servicedesk_create_incident(
        short_description="Failed sign-in attempts on break-glass account bg-admin-01 from an external IP",
        description=f"{len(failures)} failed password attempts on bg-admin-01 from {ip} between 23:51 and 23:55 on "
                    "2026-10-06, before and unrelated to emergency change CHG1203.",
        category="security", priority="2", assignment_group="GRP-SEC")

    api.siem_add_alert_note(id="A-310", text="Legitimate use under approved emergency change CHG1203 (SSO signing "
                            "certificate). KB0450 after-use steps done: password rotated and old version revoked, "
                            "sessions revoked, temporary admin removed. Failed attempts from " + ip + " raised separately.")
    api.siem_update_alert(id="A-310", status="closed", classification="benign_positive")
    return "Break-glass use matched CHG1203; after-use steps completed; failed external attempts raised as an incident."
