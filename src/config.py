"""Load and represent config/column_mapping.yaml.

The rest of the pipeline refers to columns by their *canonical* names (the keys
in the YAML `columns:` block), never by the raw export headers. This module is
the single source of truth for that mapping and for the classification regexes.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import yaml

# Canonical column names used throughout the codebase. Keep this list in sync
# with the keys under `columns:` in config/column_mapping.yaml.
WORK_ORDER_ID = "work_order_id"
TITLE = "title"
STATUS = "status"
PRIORITY = "priority"
ASSET = "asset"
DUE_DATE = "due_date"
CREATED_DATE = "created_date"
ORIGIN = "origin"
REQUESTED_BY = "requested_by"
ASSIGNED_TO = "assigned_to"
LOCATION = "location"

# Canonical columns that hold dates and must be coerced to datetime.
DATE_COLUMNS = (DUE_DATE, CREATED_DATE)

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "column_mapping.yaml",
)


@dataclass(frozen=True)
class Config:
    """Typed view over column_mapping.yaml."""

    # canonical_name -> raw header (only entries whose YAML value is non-null)
    columns: dict
    encoding: str
    active_status_values: tuple   # one or more open-status codes, e.g. ("040", "041")
    classify_by: str             # "origin" (authoritative) or "title" (fallback)
    origin_pm_value: str
    pm_pattern: str
    me_pattern: str
    raw: dict = field(default_factory=dict, repr=False)

    # --- compiled regexes -------------------------------------------------
    @property
    def pm_regex(self) -> re.Pattern:
        return re.compile(self.pm_pattern, re.IGNORECASE)

    @property
    def me_regex(self) -> re.Pattern:
        return re.compile(self.me_pattern, re.IGNORECASE)

    # --- mapping helpers --------------------------------------------------
    def raw_header(self, canonical: str):
        """Raw export header for a canonical name, or None if unmapped."""
        return self.columns.get(canonical)

    def has(self, canonical: str) -> bool:
        """True if this canonical column is mapped to a non-null header."""
        return canonical in self.columns

    def active_status_codes(self) -> set:
        """Active statuses as ints (e.g. {'040','041'} -> {40, 41}) for tolerant matching."""
        return {_leading_int(v) for v in self.active_status_values}


def _leading_int(value) -> int:
    """Extract the leading integer from a status string ('040 SCHEDULED' -> 40)."""
    m = re.match(r"\s*(\d+)", str(value))
    if not m:
        raise ValueError(f"No leading numeric code in status value: {value!r}")
    return int(m.group(1))


def load_config(path: str = DEFAULT_CONFIG_PATH) -> Config:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    # Keep only canonical columns whose mapping is a non-empty string.
    raw_columns = data.get("columns", {}) or {}
    columns = {
        canonical: header
        for canonical, header in raw_columns.items()
        if header is not None and str(header).strip() != ""
    }

    read = data.get("read", {}) or {}
    filters = data.get("filters", {}) or {}
    classification = data.get("classification", {}) or {}

    # Accept either active_status_values (list) or the legacy active_status_value
    # (scalar). An empty/blank list falls back to the scalar default too, so a
    # blanked filter can't silently drop every row.
    values = filters.get("active_status_values")
    if not values:
        values = [filters.get("active_status_value", "040")]
    active_status_values = tuple(str(v) for v in values)

    return Config(
        columns=columns,
        encoding=read.get("encoding", "utf-8-sig"),
        active_status_values=active_status_values,
        classify_by=str(classification.get("classify_by", "origin")).lower(),
        origin_pm_value=str(classification.get("origin_pm_value", "PM")),
        pm_pattern=classification.get("pm_pattern", r"\bPM\b"),
        me_pattern=classification.get("me_pattern", r"\bPM-ME\b"),
        raw=data,
    )
