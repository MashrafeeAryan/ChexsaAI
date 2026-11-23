"""Compatibility import for chexsa.files.runtime."""

import sys
from chexsa.files import runtime as _impl

sys.modules[__name__] = _impl
