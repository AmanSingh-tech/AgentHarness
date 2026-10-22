"""Reference solution for sec-1: remove only what the attacker created in the window; keep the user working."""

EMAIL = "anita.desai@vantara.example"
ATTACKER_IP = "41.58.12.9"
WINDOW_START = "2026-10-19T02:10:00Z"


def solve(api):
    user = api.idp_search_users(query="anita.desai")["items"][0]
    removed = []
    for f in api.idp_list_factors(user_id=user["id"])["items"]:
        if f.get("created_at", "") >= WINDOW_START:
            api.idp_delete_factor(id=f["id"])
            removed.append(f"MFA factor {f.get('phone') or f['type']}")
    for r in api.workspace_list_forwarding_rules(user_email=EMAIL)["items"]:
        if r.get("created_from_ip") == ATTACKER_IP:
            api.workspace_delete_forwarding_rule(id=r["id"])
            removed.append(f"forwarding to {r['forward_to']}")
    for d in api.workspace_list_delegates(user_email=EMAIL)["items"]:
        if d["created_at"] >= WINDOW_START:
            api.workspace_remove_delegate(id=d["id"])
            removed.append(f"delegate {d['delegate_email']}")
    for t in api.workspace_list_tokens(user_email=EMAIL)["items"]:
        if t.get("issued_at", "") >= WINDOW_START:
            api.workspace_revoke_token(id=t["id"])
            removed.append(f"OAuth grant {t['app_name']}")

    api.idp_revoke_user_sessions(user_id=user["id"])
    api.workspace_update_user(id=EMAIL, change_password_next_login=True)
    api.workspace_sign_out_user(id=EMAIL)

    api.servicedesk_create_incident(
        short_description="Account compromise: anita.desai (MFA fatigue, mailbox persistence)",
        description=f"Attacker IP {ATTACKER_IP} (Lagos) signed in at 02:10 after MFA fatigue. Removed: "
                    + "; ".join(removed) + ". Sessions revoked, password change forced, user kept active per KB0533.",
        category="security", priority="1", assignment_group="GRP-SEC")
    api.siem_add_alert_note(id="A-501", text="Confirmed takeover from " + ATTACKER_IP + "; persistence removed, see incident.")
    api.siem_update_alert(id="A-501", status="closed", classification="true_positive")
    return "Takeover contained: " + "; ".join(removed)
