"""Reference solution for grc-3: two independent tests per approved vendor (KB2380)."""

TODAY = "2026-11-09"


def solve(api):
    changed = []
    for v in api.grc_list_vendors(status="approved")["items"]:
        sensitive = bool({"personal", "health"} & set(v.get("data_types") or []))
        problems = []
        if sensitive and (v.get("dpa_expires") or "") < TODAY:
            problems.append("DPA expired")
        if v["tier"] in ("critical", "high") and (v.get("security_report_expires") or "") < TODAY:
            problems.append("security report expired")
        if not problems:
            continue
        api.grc_update_vendor(id=v["id"], status="under_review", notes="; ".join(problems) + " (KB2380)")
        api.grc_create_finding(title=f"{v['name']}: {', '.join(problems)}", severity="high" if sensitive else "medium",
                               vendor_id=v["id"], owner=v["owner"])
        changed.append(f"{v['name']} ({', '.join(problems)})")
    api.servicedesk_update_incident(id="INC2380", state="resolved",
                                    close_notes="Under review with findings: " + "; ".join(changed) + ".")
    return "; ".join(changed)
