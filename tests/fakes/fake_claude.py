#!/usr/bin/env python3
"""Stand-in for `claude -p` in tests: connects to the --mcp-config server with the real MCP
client, performs a scripted plan, and prints a Claude Code style JSON result.

FAKE_CLAUDE_PLAN: path to a JSON list of [tool, args] steps. FAKE_CLAUDE_ARGV: where to dump argv.
"""

import asyncio
import json
import os
import sys


async def main() -> None:
    argv = sys.argv[1:]
    if os.environ.get("FAKE_CLAUDE_ARGV"):
        with open(os.environ["FAKE_CLAUDE_ARGV"], "w") as f:
            json.dump({"argv": argv, "cwd": os.getcwd()}, f)
    config = json.load(open(argv[argv.index("--mcp-config") + 1]))
    url = config["mcpServers"]["agentguard"]["url"]
    plan = json.load(open(os.environ["FAKE_CLAUDE_PLAN"]))

    from mcp import Client

    async with Client(url) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert "submit_result" in names and "issue_refund" in names, names
        for tool, args in plan:
            await client.call_tool(tool, args)
    print("log line that is not JSON")
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "All done.",
                      "num_turns": len(plan), "total_cost_usd": 0.0123,
                      "usage": {"input_tokens": 900, "output_tokens": 120, "cache_read_input_tokens": 100}}))


asyncio.run(main())
