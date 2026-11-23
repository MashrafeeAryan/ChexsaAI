"""Compatibility import for chexsa.browser.agent."""

import sys
from chexsa.browser import agent as _impl

sys.modules[__name__] = _impl
