"""Load pipeline paths from config.yaml (the real, git-ignored file) with
built-in repo-relative defaults as a fallback.

Keeps machine-specific Teams/SharePoint paths out of the repo:
  - config.example.yaml  -> committed TEMPLATE (documentation; never auto-loaded)
  - config.yaml          -> the real file on each machine (git-ignored)

When config.yaml is absent (e.g. CI, this cloud sandbox, a fresh clone), the
defaults below keep the synthetic demo working without any Teams folders.

Read-only with respect to the PCM.
"""
from __future__ import annotations
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Repo-relative fallbacks so the demo runs anywhere without a config.yaml.
DEFAULTS = {
    "inbox_dir":   str(ROOT / "samples"),
    "runs_dir":    str(ROOT / "samples" / "runs"),
    "reports_dir": str(ROOT / "reports_out"),
    "db_path":     "tunetrack.db",
}


def load_config() -> dict:
    """Return the resolved config: DEFAULTS overridden by config.yaml if present.
    config.example.yaml is a template and is intentionally NOT loaded."""
    cfg = dict(DEFAULTS)
    real = ROOT / "config.yaml"
    if real.exists():
        loaded = yaml.safe_load(real.read_text()) or {}
        cfg.update({k: v for k, v in loaded.items() if v is not None})
    # db_path is repo-relative unless an absolute path is given.
    dbp = pathlib.Path(str(cfg["db_path"]))
    cfg["db_path"] = str(dbp if dbp.is_absolute() else ROOT / dbp)
    return cfg
