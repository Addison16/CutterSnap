"""CutterSnap: turn a cookie photo into a printable cookie cutter."""
from .cutter import CutterParams, build_cutter
from .outline import Outline, OutlineError, check_outline, mask_to_outline
from .segment import segment

__all__ = ["CutterParams", "Outline", "OutlineError", "build_cutter", "check_outline",
           "mask_to_outline", "segment"]
__version__ = "0.1.0"
