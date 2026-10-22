"""Taint tracking unit tests: direct, base64, hex and split flows match; benign flows do not."""

import base64

from agentguard.core.models import DataLabel, ToolCall, ToolResult
from agentguard.shield.taint import TaintTracker
from agentguard.world.support.tools import SUPPORT_TOOLS

SPECS = {t.name: t for t in SUPPORT_TOOLS}
VALUE = "TESTVALUE-0000-ABCD-1234-WXYZ"  # placeholder for a sensitive value


def _call(tool, args, seq):
    return ToolCall(run_id="r", agent_id="a", tool=tool, args=args, seq=seq)


def _labelled(tracker, tool, args, output, labels, seq=1, inherited=None):
    call = _call(tool, args, seq)
    result = ToolResult(call_id=call.id, tool=tool, ok=True, output=output, labels=list(labels))
    return tracker.label(call, SPECS[tool], result, inherited)


def _tracker_with_value():
    t = TaintTracker()
    _labelled(t, "read_secret", {"name": "test_key"}, {"name": "test_key", "value": VALUE}, [DataLabel.SECRET])
    return t


def test_direct():
    [m] = _tracker_with_value().match({"body": f"value is {VALUE}"})
    assert m.how == "whole_value" and m.form == "raw" and DataLabel.SECRET in m.record.labels


def test_base64():
    encoded = base64.b64encode(VALUE.encode()).decode()
    [m] = _tracker_with_value().match({"body": f"blob: {encoded}"})
    assert m.how == "whole_value"  # digest of the base64 form


def test_hex():
    [m] = _tracker_with_value().match({"body": VALUE.encode().hex()})
    assert m.how == "whole_value"


def test_encoded_fragment_is_decoded():
    # part of the value, encoded: no whole-value digest exists, so the decoder must find it
    [m] = _tracker_with_value().match({"body": base64.b64encode(VALUE[:16].encode()).decode()})
    assert m.form == "base64" and m.how == "substring"


def test_split_across_two_calls():
    t = _tracker_with_value()
    half = len(VALUE) // 2
    assert t.match({"body": VALUE[:half]})
    assert t.match({"body": VALUE[half:]})


def test_transform_propagates_chain():
    t = _tracker_with_value()
    inherited = t.match({"text": VALUE})
    encoded = base64.b64encode(VALUE.encode()).decode()
    rec = _labelled(t, "encode", {"text": VALUE, "scheme": "base64"}, {"encoded": encoded, "scheme": "base64"},
                    [], seq=2, inherited=inherited)
    assert rec is not None and [h.tool for h in rec.chain] == ["read_secret", "encode"]
    assert DataLabel.SECRET in rec.labels


def test_benign_no_false_positives():
    t = _tracker_with_value()
    # the value's name (the agent already knew it) and ordinary text do not match
    assert t.match({"body": "test_key rotated as planned"}) == []
    assert t.match({"body": "Your refund of ₹5000 for order O-9001 is processed."}) == []
    assert t.match({"body": base64.b64encode(b"hello world, nothing here").decode()}) == []
    # unlabelled results are not tracked at all
    assert _labelled(t, "get_order", {"order_id": "O-1"}, {"id": "O-1", "status": "delivered here"}, []) is None


def test_bulk_needs_several_rows():
    t = TaintTracker()
    rows = [{"name": f"Person Number{i}", "email": f"person{i}@customer-domain.com"} for i in range(10)]
    _labelled(t, "query_database", {"sql": "SELECT name, email FROM customers"}, {"rows": rows}, [DataLabel.PII_BULK])
    # one customer's own details: not bulk
    assert t.match({"to": "person1@customer-domain.com", "body": "Hi Person Number1"}) == []
    [m] = t.match({"body": str(rows[:4])})
    assert m.how == "bulk_rows" and m.rows == 4
