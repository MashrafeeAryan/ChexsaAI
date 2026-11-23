"""Compatibility entry point for chexsa.interfaces.cli."""

if __name__ == "__main__":
    from chexsa.interfaces.cli import main
    main()
else:
    import sys
    from chexsa.interfaces import cli as _impl
    sys.modules[__name__] = _impl
