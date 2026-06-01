"""Smoke test: project skeleton wiring."""
import lyrebird


def test_package_importable():
    assert lyrebird.__version__ == "0.1.0"
