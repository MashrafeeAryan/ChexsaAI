"""Compatibility import for chexsa.core.metrics."""

import sys
from chexsa.core.metrics import *
from chexsa.core.metrics import __dict__ as _module_dict

# Keep legacy imports and patch-based tests pointed at the packaged module.
_current = sys.modules[__name__]
_current.__dict__.update(_module_dict)
