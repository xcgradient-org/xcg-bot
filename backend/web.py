from __future__ import annotations

from pathlib import Path

from backend.config import ROOT


def frontend_dist_root() -> Path:
    return ROOT / "frontend" / "dist"


def legacy_redirects() -> dict[str, str]:
    return {
        "/task creator": "/task-creator",
        "/task creator/": "/task-creator",
        "/okr creator": "/okr-creator",
        "/okr creator/": "/okr-creator",
        "/meeting creator": "/meeting-creator",
        "/meeting creator/": "/meeting-creator",
        "/log": "/",
        "/log/": "/",
        "/log-creator": "/",
        "/log-creator/": "/",
        "/log creator": "/",
        "/log creator/": "/",
        "/weekly rollover": "/",
        "/weekly rollover/": "/",
    }
