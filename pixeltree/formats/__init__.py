"""Compact tree formats (F0 / F1 / F3) and the optional, experimental name cleaning (F2).

Every public function and constant is re-exported under its original name, so `from pixeltree import formats as F`
gives `F.f0`, `F.f1`, `F.f2`, `F.clean`, `F.Delta3`, `F.Decoder3`, `F.f2_keys`, `F.one_line`, ...

Assigning a threshold on this package (`F.MATCH_MOVE_PX = 60`) is forwarded to the submodule that uses it
(`core` for the change encoding, `clean` for the cleaning rules), so tuning code written against a flat module keeps
working.

The cleaning rules are experimental and off by default: see `pixeltree.formats.clean`.
"""
import sys
import types

from . import clean as _clean_mod
from . import core as _core_mod
from .clean import (CONTAIN_FRAC, CONTAINER_MIN_TEXTS, DEFAULT_RANK, DUP_IOU, DUP_NAME_SIM, ICON_MAX_SIDE, ODD_MODE,
                    ROLE_RANK, SYMBOL_ONLY_BLANK, TEXT_ROLES, clean, f2, fix_name, strip_odd)
from .core import (FULL_IF_CHANGED_FRAC, MATCH_MOVE_PX, MATCH_RENAME_IOU, SHORT_ROLE, Decoder3, Delta3, box_area,
                   center, esc, f0, f1, f1_line, f2_keys, inside_frac, inter, iou, key, match, name_sim, norm,
                   one_line, short_role, unesc)

__all__ = [
    "SHORT_ROLE", "TEXT_ROLES", "ROLE_RANK", "DEFAULT_RANK", "ICON_MAX_SIDE", "ODD_MODE", "SYMBOL_ONLY_BLANK",
    "CONTAINER_MIN_TEXTS", "CONTAIN_FRAC", "DUP_NAME_SIM", "DUP_IOU", "MATCH_MOVE_PX", "MATCH_RENAME_IOU",
    "FULL_IF_CHANGED_FRAC",
    "box_area", "inter", "iou", "inside_frac", "center", "norm", "name_sim", "one_line", "esc", "unesc", "short_role",
    "f0", "f1_line", "f1", "strip_odd", "fix_name", "clean", "f2", "key", "match", "Delta3", "Decoder3", "f2_keys",
]

_OWNERS = (_core_mod, _clean_mod)


class _Forwarding(types.ModuleType):
    """Module whose attribute assignment also reaches the submodule that owns the name."""

    def __setattr__(self, name, value):
        for mod in _OWNERS:
            if name in vars(mod) and not name.startswith("__"):
                setattr(mod, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Forwarding
