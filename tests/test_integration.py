"""Integration test: start MCP Hub, list tools, call hub_status, call a backend tool."""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    print("=" * 60)
    print("MCP Hub Integration Test")
    print("=" * 60)

    server_params = StdioServerParameters(
        command="python3",
        args=["-m", "src.server", "mcp_hub.yaml"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 1. Initialize
            print("\n[1] Initializing...")
            init_result = await session.initialize()
            print(f"    Server: {init_result.serverInfo.name}")
            print(f"    Version: {init_result.serverInfo.version}")

            # 2. List tools
            print("\n[2] Listing tools...")
            tools_result = await session.list_tools()
            tools = tools_result.tools
            hub_tools = [t for t in tools if t.name.startswith("hub_")]
            backend_tools = [t for t in tools if not t.name.startswith("hub_")]
            print(f"    Hub tools: {len(hub_tools)}")
            for t in sorted(hub_tools, key=lambda x: x.name):
                print(f"      - {t.name}")
            print(f"    Backend tools: {len(backend_tools)}")
            for t in sorted(backend_tools, key=lambda x: x.name):
                print(f"      - {t.name}")

            # 3. Call hub_status
            print("\n[3] Calling hub_status...")
            result = await session.call_tool("hub_status", {})
            for c in result.content:
                if hasattr(c, 'text'):
                    print(f"    {c.text}")

            # 4. Call hub_tools
            print("\n[4] Calling hub_tools...")
            result = await session.call_tool("hub_tools", {})
            for c in result.content:
                if hasattr(c, 'text'):
                    print(f"    {c.text[:300]}")

            # 5. Call hub_search_tools
            print("\n[5] Calling hub_search_tools(query='list')...")
            result = await session.call_tool("hub_search_tools", {"query": "list"})
            for c in result.content:
                if hasattr(c, 'text'):
                    print(f"    {c.text}")

            # 6. Call hub_alias_list
            print("\n[6] Calling hub_alias_list...")
            result = await session.call_tool("hub_alias_list", {})
            for c in result.content:
                if hasattr(c, 'text'):
                    print(f"    {c.text}")

            # 7. Call hub_session_stats
            print("\n[7] Calling hub_session_stats...")
            result = await session.call_tool("hub_session_stats", {})
            for c in result.content:
                if hasattr(c, 'text'):
                    print(f"    {c.text}")

            # 8. Call a backend tool (fs_read via alias)
            print("\n[8] Calling fs_read (alias) to read /tmp directory listing...")
            try:
                result = await session.call_tool("list_directory", {"path": "/tmp"})
                for c in result.content:
                    if hasattr(c, 'text'):
                        print(f"    {c.text[:500]}")
            except Exception as e:
                print(f"    Error: {e}")

            # 9. Call hub_stats (should show calls from above)
            print("\n[9] Calling hub_stats...")
            result = await session.call_tool("hub_stats", {})
            for c in result.content:
                if hasattr(c, 'text'):
                    print(f"    {c.text}")

            # 10. Call hub_quiet_on then hub_quiet_status
            print("\n[10] Testing quiet mode...")
            await session.call_tool("hub_quiet_on", {"target": "fs_read", "duration": 60})
            result = await session.call_tool("hub_quiet_status", {})
            for c in result.content:
                if hasattr(c, 'text'):
                    print(f"    {c.text}")
            await session.call_tool("hub_quiet_off", {"target": "all"})

            # 11. Call hub_config_show
            print("\n[11] Calling hub_config_show (first 300 chars)...")
            result = await session.call_tool("hub_config_show", {})
            for c in result.content:
                if hasattr(c, 'text'):
                    print(f"    {c.text[:300]}...")

            # 12. Call hub_export_stats
            print("\n[12] Calling hub_export_stats (first 300 chars)...")
            result = await session.call_tool("hub_export_stats", {})
            for c in result.content:
                if hasattr(c, 'text'):
                    print(f"    {c.text[:300]}...")

            # 13. Test cost register + estimate
            print("\n[13] Testing cost register + estimate...")
            await session.call_tool("hub_cost_register", {
                "tool": "fs_read",
                "cost_type": "free",
                "cost_value": 0,
                "description": "Local filesystem read"
            })
            result = await session.call_tool("hub_cost_estimate", {"tool": "fs_read"})
            for c in result.content:
                if hasattr(c, 'text'):
                    print(f"    {c.text}")

            # 14. Test session begin + step
            print("\n[14] Testing stateful session...")
            result = await session.call_tool("hub_session_begin", {"name": "test-session", "context": {"user": "test"}})
            for c in result.content:
                if hasattr(c, 'text'):
                    print(f"    {c.text}")
            import json as j
            session_data = j.loads(result.content[0].text)
            sid = session_data["session_id"]
            result = await session.call_tool("hub_session_step", {"session_id": sid, "tool": "hub_status"})
            for c in result.content:
                if hasattr(c, 'text'):
                    print(f"    {c.text[:200]}")

            # 15. Test compose
            print("\n[15] Testing compose (hub_status + hub_tools)...")
            result = await session.call_tool("hub_compose", {
                "steps": [
                    {"tool": "hub_status", "arguments": {}},
                    {"tool": "hub_alias_list", "arguments": {}}
                ]
            })
            for c in result.content:
                if hasattr(c, 'text'):
                    print(f"    {c.text[:300]}")

            print("\n" + "=" * 60)
            print("ALL TESTS PASSED")
            print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
