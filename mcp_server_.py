"""Let another assistant use Chexsa's file tools in one chosen folder."""

import argparse
from pathlib import Path
from typing import Any

import files_


def file_path(folder, name):
    """Turn reports/note.txt into a path under the folder the user chose."""
    path = Path(name)
    if (
        not name.strip() or path.anchor or ":" in name
        or any(Path(part).is_reserved() for part in path.parts)
    ):
        raise ValueError("Give a file path relative to the chosen folder.")
    target = (folder / path).resolve()
    # Resolve links first so they cannot point the tool outside the folder.
    if target == folder or not target.is_relative_to(folder):
        raise ValueError("Choose a file inside the shared folder.")
    return target


def build_server(folder):
    """Set up tools for exactly one folder."""
    from mcp.server.fastmcp import FastMCP

    folder = Path(folder).resolve(strict=True)
    if not folder.is_dir():
        raise ValueError("Choose an existing folder.")
    server = FastMCP("Chexsa Files")

    @server.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def read_section(path: str, query: str = "") -> dict[str, Any]:
        """Read a short excerpt. Use a phrase or function name, or blank for the start."""
        return files_.read_file_section(file_path(folder, path), query)

    @server.tool(annotations={"destructiveHint": False, "openWorldHint": False})
    def create_file(path: str, content: str) -> dict[str, Any]:
        """Save a new text, Python, or Word file. Existing files stay untouched."""
        target = file_path(folder, path)
        try:
            saved = files_.write_file(str(target), content)
        except FileExistsError:
            raise ValueError("That file already exists. Choose a new name.") from None
        except SyntaxError:
            raise ValueError("The Python text has a syntax error.") from None
        return {"path": Path(saved).relative_to(folder).as_posix(), "saved": True}

    return server


def main():
    """Start the server over the local connection opened by the MCP client."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", required=True, help="Existing folder to share with the client.")
    args = parser.parse_args()
    try:
        server = build_server(args.folder)
    except ModuleNotFoundError as error:
        if error.name != "mcp":
            raise
        parser.exit(1, 'Install MCP support with python -m pip install -e ".[mcp]"\n')
    except (OSError, ValueError):
        parser.error("Choose an existing folder with --folder.")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
