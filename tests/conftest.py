"""Configure pytest: load source modules as a package so relative imports resolve."""

import importlib.util
import sys
import types
from pathlib import Path

_SRC = Path(__file__).parent.parent / "src" / "idi-ftm2j-shared"
_PKG = "_idi_ftm2j_shared"


def _bootstrap() -> None:
    """Load source modules as package members and register top-level aliases.

    api.py uses `from .logs import get_logger` (relative import), which requires
    the module's __package__ to be set. We create a synthetic package and load
    each module under it, then alias each name so tests can do `import logs` etc.
    """
    if _PKG in sys.modules:
        return

    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [str(_SRC)]
    pkg.__package__ = _PKG
    sys.modules[_PKG] = pkg

    # Stub idi_corporate_structure so failures.py can be imported without the package installed.
    # Tests patch failures.load_json / failures.save_json directly.
    for stub in (
        "idi_corporate_structure",
        "idi_corporate_structure.common",
        "idi_corporate_structure.common.storage",
    ):
        if stub not in sys.modules:
            sys.modules[stub] = types.ModuleType(stub)
    from unittest.mock import MagicMock

    sys.modules["idi_corporate_structure.common.storage"].load_json = MagicMock()
    sys.modules["idi_corporate_structure.common.storage"].save_json = MagicMock()

    for name in ("logs", "storage", "api", "failures"):
        fqn = f"{_PKG}.{name}"
        spec = importlib.util.spec_from_file_location(fqn, _SRC / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = _PKG
        sys.modules[fqn] = mod
        sys.modules[name] = mod
        spec.loader.exec_module(mod)


_bootstrap()
