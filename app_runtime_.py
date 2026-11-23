"""Compatibility import for chexsa.app.runtime."""

import sys
from chexsa.app import runtime as _impl

sys.modules[__name__] = _impl
