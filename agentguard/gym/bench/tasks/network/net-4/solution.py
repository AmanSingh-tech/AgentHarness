"""Reference solution for net-4: decommission the reporting tier, but leave rpt-02's billing role intact."""

HOSTS = ("rpt-01", "rpt-02")


def solve(api):
    vs = next(v for v in api.lb_list_virtual_servers()["items"] if v["name"] == "reports")
    api.lb_update_virtual_server(id=vs["id"], status="disabled")
    for m in api.lb_list_members(pool_id=vs["pool_id"])["items"]:
        api.lb_disable_member(id=m["id"])

    still_serving = {}
    for host in HOSTS:
        others = [m for m in api.lb_list_members(host=host)["items"] if m["pool_id"] != vs["pool_id"]]
        if others:
            still_serving[host] = sorted({api.lb_get_pool(id=m["pool_id"])["name"] for m in others})

    for r in api.dns_list_records(zone="nimbusbank.example", name="reports")["items"]:
        api.dns_delete_record(id=r["id"])
    for host in HOSTS:
        device = api.assets_search_devices(query=host)["items"][0]
        if host not in still_serving:
            api.assets_update_device(id=device["id"], status="retired", notes=device["notes"] + " - retired CHG4100")

    note = "Reports VIP disabled, reporting-pool members disabled, reports DNS deleted, rpt-01 retired."
    for host, pools in still_serving.items():
        note += f" NOT retired: {host} is still a live member of {', '.join(pools)} (billing) - migrate billing first."
    api.servicedesk_add_change_note(id="CHG4100", text=note)
    return note
