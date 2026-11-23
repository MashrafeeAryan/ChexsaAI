"""Compatibility entry point for chexsa.mcp.server."""

if __name__ == "__main__":
    from chexsa.mcp.server import main
    main()
else:
    import sys
    from chexsa.mcp import server as _impl
    sys.modules[__name__] = _impl
