"""Compatibility import for chexsa.core.metrics."""

import sys
from chexsa.core import metrics as _impl

sys.modules[__name__] = _impl
