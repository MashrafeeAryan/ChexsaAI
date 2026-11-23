"""Compatibility entry point for chexsa.app.ui."""

if __name__ == "__main__":
    from chexsa.app.ui import main
    main()
else:
    import sys
    from chexsa.app import ui as _impl
    sys.modules[__name__] = _impl
