"""Reference solution for off-2: find every residual access path of the two Vexa contractors."""

END = "2026-09-30"


def solve(api):
    leavers = [w for w in api.hr_list_workers(worker_type="contractor", status="terminated")["items"]
               if "Vexa" in (w.get("notes") or "")]
    found = []
    for w in leavers:
        vexa = w["notes"].split("(")[1].rstrip(")")
        for email in (w["email"], vexa):
            for m in api.codehost_search_members(query=email)["items"]:
                if m["email"] != email:
                    continue
                for t in api.codehost_list_tokens(member_id=m["id"])["items"]:
                    api.codehost_revoke_token(id=t["id"])
                for k in api.codehost_list_deploy_keys(added_by=m["login"])["items"]:
                    if "pipeline" in k["title"]:
                        api.grc_create_finding(
                            title=f"Re-issue deploy key '{k['title']}' added by departed contractor {m['login']}",
                            severity="high", owner="Platform", notes=f"release-pipeline key {k['id']} on {k['repo_id']} "
                            "was added by a Vexa contractor who left on 2026-09-30; kept to avoid breaking releases.")
                    else:
                        api.codehost_delete_deploy_key(id=k["id"])
                api.codehost_remove_member(id=m["id"])
                found.append(f"code hosting {m['login']}")
            for p in api.files_list_permissions(principal=email)["items"]:
                api.files_remove_permission(id=p["id"])
                found.append(f"site permission {p['id']}")
        ws = api.workspace_get_user(id=w["email"])
        if not ws["suspended"]:
            api.workspace_suspend_user(id=w["email"])
            found.append(f"workspace {w['email']}")
        for rule in api.workspace_list_forwarding_rules(user_email=w["email"])["items"]:
            api.workspace_delete_forwarding_rule(id=rule["id"])
            found.append(f"forwarding to {rule['forward_to']}")

        login = w["email"].split("@")[0]
        for entry in api.vault_list_access_log(actor=login)["items"]:
            if entry["at"][:10] > END:
                versions = api.vault_list_versions(secret_id=entry["secret_id"])["items"]
                api.vault_rotate_secret(secret_id=entry["secret_id"], version=max(v["version"] for v in versions) + 1)
                api.vault_revoke_version(id=entry["version_id"])
                api.servicedesk_create_incident(
                    short_description=f"Departed contractor {login} read secret {entry['secret_id']} after leaving",
                    description=f"{login} read {entry['secret_id']} ({entry['version_id']}) on {entry['at']} from "
                                f"{entry['src_ip']}, after the engagement ended on {END}. Rotated and revoked.",
                    category="security", priority="2", assignment_group="GRP-SEC")
                found.append(f"secret {entry['secret_id']} rotated")

    api.servicedesk_update_incident(id="INC0842", state="resolved",
                                    close_notes="Residual access removed: " + "; ".join(found) + ".")
    return "Removed residual access: " + "; ".join(found)
