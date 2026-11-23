"""Compatibility import for chexsa.browser.runtime."""

import sys
from chexsa.browser import runtime as _impl

sys.modules[__name__] = _impl
