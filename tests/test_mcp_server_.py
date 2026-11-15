"""Start a real MCP subprocess and try it with disposable files."""

import asyncio
from importlib.util import find_spec
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import FunctionTestCase, TestSuite, skipUnless


async def exercise(folder, check):
    """Connect as a real MCP client and give the test a session."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    script = Path(__file__).resolve().parents[1] / "mcp_server_.py"
    params = StdioServerParameters(
        command=sys.executable, args=[str(script), "--folder", str(folder)],
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            await check(session)


def test_read_section_and_folder_boundary():
    """Read one function and block paths outside the chosen folder."""
    with TemporaryDirectory() as directory:
        outside = Path(directory)
        folder = outside / "shared"
        folder.mkdir()
        (folder / "example.py").write_text("def fib(n):\n    return n\n", encoding="utf-8")
        (outside / "private.txt").write_text("Private fixture", encoding="utf-8")

        async def check(session):
            """Use MCP for both the read and the rejected requests."""
            tools = await session.list_tools()
            assert "read_section" in {tool.name for tool in tools.tools}
            result = await session.call_tool("read_section", {"path": "example.py", "query": "fib"})
            assert not result.isError
            assert result.structuredContent["text"] == "def fib(n):\n    return n"
            for path in ("../private.txt", str(outside / "private.txt"), "example.py:other"):
                denied = await session.call_tool("read_section", {"path": path})
                assert denied.isError and "Private fixture" not in str(denied.content)

        asyncio.run(asyncio.wait_for(exercise(folder, check), timeout=25))



def test_create_file_keeps_existing_content():
    """The client can save a verified file and cannot overwrite it."""
    with TemporaryDirectory() as directory:
        folder = Path(directory)

        async def check(session):
            """Try the same name twice."""
            args = {"path": "notes.txt", "content": "First note"}
            result = await session.call_tool("create_file", args)
            assert not result.isError, result.content
            assert result.structuredContent == {"path": "notes.txt", "saved": True}
            denied = await session.call_tool("create_file", {**args, "content": "Second note"})
            assert denied.isError
            assert (folder / "notes.txt").read_text(encoding="utf-8") == "First note"

        asyncio.run(asyncio.wait_for(exercise(folder, check), timeout=25))


def load_tests(loader, tests, pattern):
    """Run the fixtures when the optional SDK is installed."""
    needs_sdk = skipUnless(find_spec("mcp"), "Install the MCP extra for these tests.")
    return TestSuite(FunctionTestCase(needs_sdk(test)) for name, test in globals().items() if name.startswith("test_"))
