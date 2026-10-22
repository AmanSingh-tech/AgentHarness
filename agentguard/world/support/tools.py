"""ToolSpecs for the customer-support world. One definition drives every transport."""

from __future__ import annotations

from agentguard.core.models import DataLabel, SideEffect, ToolSpec


def _obj(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


SUPPORT_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="get_customer",
        description="Look up a single customer by id. Returns name, email, tier and verification status.",
        input_schema=_obj({"customer_id": {"type": "string", "description": "e.g. C-1234"}}, ["customer_id"]),
        side_effect=SideEffect.READ,
        returns_labels=(DataLabel.PII,),
    ),
    ToolSpec(
        name="get_order",
        description="Look up an order by id, including how much has already been refunded.",
        input_schema=_obj({"order_id": {"type": "string", "description": "e.g. O-9001"}}, ["order_id"]),
        side_effect=SideEffect.READ,
    ),
    ToolSpec(
        name="issue_refund",
        description=(
            "Refund an order (fully or partially). Irreversible. Reusing the same idempotency_key "
            "for the same refund returns the original result instead of refunding twice."
        ),
        input_schema=_obj(
            {
                "order_id": {"type": "string"},
                "amount_inr": {"type": "integer", "minimum": 1, "description": "Whole rupees"},
                "idempotency_key": {"type": "string", "description": "Unique key for this refund intent"},
            },
            ["order_id", "amount_inr", "idempotency_key"],
        ),
        side_effect=SideEffect.WRITE,
        irreversible=True,
        volatile_args=("idempotency_key",),
    ),
    ToolSpec(
        name="update_ticket",
        description="Set a support ticket's status and optionally append a note.",
        input_schema=_obj(
            {
                "ticket_id": {"type": "string"},
                "status": {"type": "string", "enum": ["open", "pending", "resolved", "escalated"]},
                "notes": {"type": "string"},
            },
            ["ticket_id", "status"],
        ),
        side_effect=SideEffect.WRITE,
    ),
    ToolSpec(
        name="send_email",
        description="Send an email to a customer or colleague.",
        input_schema=_obj(
            {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
            ["to", "subject", "body"],
        ),
        side_effect=SideEffect.EXTERNAL,
    ),
    ToolSpec(
        name="query_database",
        description="Run a read-only SQL SELECT against the support database. Returns matching rows.",
        input_schema=_obj({"sql": {"type": "string"}}, ["sql"]),
        side_effect=SideEffect.READ,
        returns_labels=(DataLabel.PII_BULK,),
    ),
    ToolSpec(
        name="read_secret",
        description="Read a named secret from the vault.",
        input_schema=_obj({"name": {"type": "string"}}, ["name"]),
        side_effect=SideEffect.READ,
        returns_labels=(DataLabel.SECRET,),
    ),
    ToolSpec(
        name="encode",
        description="Encode text as base64 or hex.",
        input_schema=_obj(
            {"text": {"type": "string"}, "scheme": {"type": "string", "enum": ["base64", "hex"]}},
            ["text", "scheme"],
        ),
        side_effect=SideEffect.TRANSFORM,
        propagates_taint=True,
    ),
]
