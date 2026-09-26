"""Tests unitaires — scripts/check_infrastructure.py (sans Docker)"""
import pytest

from scripts.check_infrastructure import _is_at_least, _version_tuple


@pytest.mark.parametrize("version,attendu", [
    ("8.0.36", (8, 0, 36)),
    ("15.6 (Debian 15.6-1.pgdg120+2)", (15, 6)),
    ("6.0.14", (6, 0, 14)),
    ("7.2.4", (7, 2, 4)),
])
def test_version_tuple(version, attendu):
    assert _version_tuple(version) == attendu


def test_versions_minimales():
    assert _is_at_least("8.0.16", (8, 0, 16))
    assert _is_at_least("8.0.36", (8, 0, 16))
    assert not _is_at_least("8.0.15", (8, 0, 16))
    assert not _is_at_least("14.9", (15,))
