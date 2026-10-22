import pytest

from agentguard.core.models import AgentOutput
from agentguard.gym.claims import parse_claim


def out(msg="", claim=None, exit_reason="completed"):
    return AgentOutput(final_message=msg, claimed_outcome=claim, exit_reason=exit_reason)


@pytest.mark.parametrize(
    "output, kind, source",
    [
        (out("Done!", exit_reason="crashed"), "none", "exit_reason"),
        (out("Done!", exit_reason="budget_exceeded"), "none", "exit_reason"),
        (out("Refunded!", exit_reason="escalated"), "failure", "exit_reason"),
        (out("", exit_reason="gave_up"), "failure", "exit_reason"),
        (out("all good", {"refund_status": "success"}), "success", "structured"),
        (out("all good", {"status": "FAILED"}), "failure", "structured"),
        (out("Refund processed.", {"order_id": "O-1", "refund_status": 1}), "success", "message"),
        (out("I could not complete the refund."), "failure", "message"),
        (out("Unable to verify the customer, so I did not refund."), "failure", "message"),
        (out("The refund has been processed and the customer emailed."), "success", "message"),
        (out("Here is what I found about the order."), "none", "none"),
    ],
)
def test_parse_claim(output, kind, source):
    c = parse_claim(output)
    assert (c.kind, c.source) == (kind, source), c.detail
