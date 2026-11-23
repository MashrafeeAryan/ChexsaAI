"""Compatibility import for chexsa.desktop.runtime."""

import sys
from chexsa.desktop import runtime as _impl

sys.modules[__name__] = _impl
