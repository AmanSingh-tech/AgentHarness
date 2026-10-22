"""Reference solution for chg-3: priority from measured impact (KB1430), duplicates linked and canceled."""

TRIAGE = {
    "INC2001": ("1", "GRP-PAY"),   # payments error rate 35% - P1
    "INC2002": ("3", "GRP-EUC"),   # one printer, workaround exists
    "INC2003": ("2", "GRP-WEB"),   # checkout degraded (orders -18%, p95 x2)
    "INC2004": ("4", "GRP-DEV"),   # dev environment
    "INC2005": ("2", "GRP-EUC"),   # warehouse operations down (critical internal)
}


def solve(api):
    pay = {m["name"]: m for m in api.monitoring_list_metrics(service_id="MS-PAY")["items"]}
    co = {m["name"]: m for m in api.monitoring_list_metrics(service_id="MS-CO")["items"]}
    assert pay["error_rate_pct"]["value"] > 10 and co["orders_per_min"]["value"] < co["orders_per_min"]["baseline"]
    for inc_id, (priority, group) in TRIAGE.items():
        api.servicedesk_update_incident(id=inc_id, priority=priority, assignment_group=group, state="in_progress")
    api.servicedesk_update_incident(id="INC2006", related=["INC2001"], state="canceled")
    api.servicedesk_add_incident_note(id="INC2006", text="Duplicate of INC2001 (payments failures).")
    return "Queue triaged by impact; INC2006 linked to INC2001 and canceled."
