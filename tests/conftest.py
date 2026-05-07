"""Configure pytest: stub external packages not installed in the test environment."""

import sys
import types
from unittest.mock import MagicMock


def _stub_external_packages() -> None:
    for stub in (
        "idi_corporate_structure",
        "idi_corporate_structure.common",
        "idi_corporate_structure.common.storage",
    ):
        if stub not in sys.modules:
            sys.modules[stub] = types.ModuleType(stub)
    sys.modules["idi_corporate_structure.common.storage"].load_json = MagicMock()
    sys.modules["idi_corporate_structure.common.storage"].save_json = MagicMock()


_stub_external_packages()
