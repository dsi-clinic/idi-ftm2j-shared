"""Smoke tests confirming both namespace import roots are installable."""


def test_import_runtime_namespace():
    import idi_ftm2j_shared  # noqa: F401


def test_import_infra_namespace():
    import idi_ftm2j_shared_infra  # noqa: F401
