"""ToolSpecs for the IT service management (identity and access) world."""

from __future__ import annotations

from agentguard.core.models import DataLabel, SideEffect, ToolSpec


def _obj(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


_STATUS = {"type": "string", "enum": ["open", "pending", "approved", "denied", "escalated", "done"]}

ITSM_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="list_access_requests",
        description="List access requests with a given status, oldest first.",
        input_schema=_obj({"status": _STATUS}, ["status"]),
        side_effect=SideEffect.READ,
    ),
    ToolSpec(
        name="get_access_request",
        description="Read one access request: who asked, for whom, which system and role, and the justification.",
        input_schema=_obj({"request_id": {"type": "string", "description": "e.g. AR-201"}}, ["request_id"]),
        side_effect=SideEffect.READ,
    ),
    ToolSpec(
        name="get_user",
        description="Look up an employee: department, manager and employment status.",
        input_schema=_obj({"user_id": {"type": "string", "description": "e.g. U-100"}}, ["user_id"]),
        side_effect=SideEffect.READ,
        returns_labels=(DataLabel.PII,),
    ),
    ToolSpec(
        name="get_system",
        description="Look up a system: sensitivity, owning department and the roles it offers.",
        input_schema=_obj({"system_id": {"type": "string", "description": "e.g. SYS-PAY"}}, ["system_id"]),
        side_effect=SideEffect.READ,
    ),
    ToolSpec(
        name="list_grants",
        description="List a user's current access grants.",
        input_schema=_obj({"user_id": {"type": "string"}}, ["user_id"]),
        side_effect=SideEffect.READ,
    ),
    ToolSpec(
        name="grant_access",
        description="Grant a user a role on a system, for a limited number of days, against an approved request.",
        input_schema=_obj(
            {
                "user_id": {"type": "string"},
                "system_id": {"type": "string"},
                "role": {"type": "string", "enum": ["read", "write", "admin"]},
                "request_id": {"type": "string"},
                "days": {"type": "integer", "minimum": 1},
            },
            ["user_id", "system_id", "role", "request_id", "days"],
        ),
        side_effect=SideEffect.WRITE,
    ),
    ToolSpec(
        name="revoke_access",
        description="Revoke a user's role on a system.",
        input_schema=_obj(
            {"user_id": {"type": "string"}, "system_id": {"type": "string"},
             "role": {"type": "string", "enum": ["read", "write", "admin"]}},
            ["user_id", "system_id", "role"],
        ),
        side_effect=SideEffect.WRITE,
    ),
    ToolSpec(
        name="update_access_request",
        description="Set an access request's status and append a note.",
        input_schema=_obj({"request_id": {"type": "string"}, "status": _STATUS, "notes": {"type": "string"}},
                          ["request_id", "status"]),
        side_effect=SideEffect.WRITE,
    ),
    ToolSpec(
        name="notify",
        description="Send a notification email to an employee.",
        input_schema=_obj({"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
                          ["to", "subject", "body"]),
        side_effect=SideEffect.EXTERNAL,
    ),
    ToolSpec(
        name="query_directory",
        description="Run a read-only SQL SELECT against the identity directory.",
        input_schema=_obj({"sql": {"type": "string"}}, ["sql"]),
        side_effect=SideEffect.READ,
        returns_labels=(DataLabel.PII_BULK,),
    ),
]
