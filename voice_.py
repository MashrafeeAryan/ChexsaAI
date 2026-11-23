"""Compatibility entry point for chexsa.interfaces.voice."""

if __name__ == "__main__":
    from chexsa.interfaces.voice import main
    main()
else:
    import sys
    from chexsa.interfaces import voice as _impl
    sys.modules[__name__] = _impl
