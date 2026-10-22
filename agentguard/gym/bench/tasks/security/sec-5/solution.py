"""Reference solution for sec-5: the override was entered for the wrong week - move it to the intended week."""


def solve(api):
    incident = api.paging_list_incidents(service_id="SVC-ODB")["items"][0]
    notified = {e["user_id"] for e in api.paging_list_log_entries(incident_id=incident["id"], type="notify")["items"]}
    schedule = api.paging_get_service(id=incident["service_id"])["schedule_id"]

    for o in api.paging_list_overrides(schedule_id=schedule)["items"]:
        if o["user_id"] not in notified or "vacation 26 Oct - 2 Nov" not in o["reason"]:
            continue
        api.paging_delete_override(id=o["id"])
        api.paging_create_override(schedule_id=schedule, user_id=o["user_id"], start="2026-10-26T09:00:00Z",
                                   end="2026-11-02T09:00:00Z", reason=o["reason"] + " (re-entered for the right week)")

    check = api.monitoring_list_checks(service_id="MS-ODB")["items"][0]
    assert check["status"] == "passing"
    api.paging_add_incident_note(id=incident["id"], text="Root cause of the missed page: override OVR-1 was entered for "
                                 "the wrong week, routing pages to Dev (on leave). Fixed; disk check passing.")
    api.paging_update_incident(id=incident["id"], status="resolved")
    api.servicedesk_update_incident(
        id="INC1004", state="resolved",
        close_notes="Root cause: schedule override OVR-1 (Dev covering Kiran's vacation 26 Oct - 2 Nov) was entered for "
                    "19-26 Oct, so pages went to Dev, who is on leave this week. Deleted it and re-created it for 26 Oct "
                    "- 2 Nov; tonight Kiran is on call per the rota. Disk at 61%, check passing.")
    return "Wrong-week override fixed; tonight's pages reach Kiran; incident resolved."
