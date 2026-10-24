"""The README's examples keep working."""

import runpy
from pathlib import Path


def test_protect_your_tools(capsys):
    main = runpy.run_path(str(Path(__file__).parents[1] / "examples" / "protect_your_tools.py"))["main"]
    outcomes = dict(main())
    out = capsys.readouterr().out
    assert outcomes["lookup_invoice"] == "ok" and outcomes["delete_vendor"].startswith("BLOCKED")
    assert "held for a human -> approved" in out and "exceeds finance_assistant's limit" in out
    assert "hash chain verified" in out
