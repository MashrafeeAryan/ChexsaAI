"""Compatibility import for chexsa.browser.model."""

import sys
from chexsa.browser import model as _impl

sys.modules[__name__] = _impl
