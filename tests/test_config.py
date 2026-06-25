"""Config loading — active-status parsing (list, legacy scalar, empty fallback)."""
from __future__ import annotations

from src.config import load_config

_BASE = """
columns:
  status: "WO Status"
read:
  encoding: "utf-8-sig"
classification:
  classify_by: origin
  origin_pm_value: "PM"
filters:
"""


def _write(tmp_path, filters_block):
    p = tmp_path / "c.yaml"
    p.write_text(_BASE + filters_block)
    return load_config(str(p))


def test_active_status_values_list(tmp_path):
    cfg = _write(tmp_path, '  active_status_values: ["040", "041"]\n')
    assert cfg.active_status_codes() == {40, 41}


def test_legacy_scalar_active_status_value(tmp_path):
    cfg = _write(tmp_path, '  active_status_value: "040"\n')
    assert cfg.active_status_codes() == {40}


def test_empty_list_falls_back_to_default(tmp_path):
    # An explicitly empty list must not silently drop every row.
    cfg = _write(tmp_path, "  active_status_values: []\n")
    assert cfg.active_status_codes() == {40}


def test_classify_by_defaults_to_origin(tmp_path):
    cfg = _write(tmp_path, '  active_status_value: "040"\n')
    assert cfg.classify_by == "origin"
    assert cfg.origin_pm_value == "PM"
