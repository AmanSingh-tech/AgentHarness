"""Reference solution for chg-1: production is the source of truth for last week's change records."""

WEEK_START, TODAY = "2026-10-26", "2026-11-02"


def solve(api):
    services = {s["id"]: s for s in api.monitoring_list_services()["items"]}
    deploys = api.monitoring_list_deploys()["items"]
    summary = []
    for c in api.servicedesk_list_changes()["items"]:
        if not (WEEK_START <= c["planned_start"][:10] < TODAY):
            continue
        mine = [d for d in deploys if d.get("change_id") == c["id"]]
        if not mine:
            state = "canceled"
        elif any(d["status"] in ("failed", "rolled_back") for d in mine):
            state = "failed"
        else:
            state = "implemented"
        if c["state"] != state:
            api.servicedesk_update_change(id=c["id"], state=state)
            summary.append(f"{c['id']} {c['state']} -> {state}")
    for d in deploys:
        if not d.get("change_id"):
            svc = services[d["service_id"]]
            api.servicedesk_create_incident(
                short_description=f"Unauthorised change: {svc['name']} {d['version']} deployed without a change",
                description=f"{svc['name']} {d['version']} was deployed to production on {d['deployed_at']} by "
                            f"{d['deployed_by']} with no change record (KB1410).",
                category="change", priority="3", assignment_group="GRP-CAB")
            summary.append(f"unauthorised {svc['name']} {d['version']} raised")
    api.servicedesk_update_incident(id="INC1402", state="resolved", close_notes="; ".join(summary))
    return "; ".join(summary)
