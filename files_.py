"""Compatibility import for chexsa.files.runtime."""

import sys
from chexsa.files.runtime import *
from chexsa.files.runtime import __dict__ as _module_dict

# Keep legacy imports and patch-based tests pointed at the packaged module.
_current = sys.modules[__name__]
_current.__dict__.update(_module_dict)
