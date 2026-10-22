"""Reference solution for grc-4: OU and licence seat for every custodian; leavers stay suspended."""


def solve(api):
    hold = api.grc_get_legal_hold(id="LH-2026-11")
    office = next(s for s in api.licenses_list_subscriptions()["items"] if s["product"] == "Office Suite")
    fixed = []
    for email in hold["custodians"]:
        user = api.workspace_get_user(id=email)
        if user["org_unit"] != "/Legal Hold":
            api.workspace_update_user(id=email, org_unit="/Legal Hold")
            fixed.append(f"{email} moved to /Legal Hold")
        if not api.licenses_list_seats(subscription_id=office["id"], user_email=email)["items"]:
            api.licenses_assign_seat(subscription_id=office["id"], user_email=email)
            fixed.append(f"{email} Office Suite seat re-assigned (mailbox would be deleted after 20 days)")
    api.servicedesk_update_incident(id="INC2410", state="resolved",
                                    close_notes="Preservation gaps fixed per KB2420: " + "; ".join(fixed) + ".")
    return "; ".join(fixed)
