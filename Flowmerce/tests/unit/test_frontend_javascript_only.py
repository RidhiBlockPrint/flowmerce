"""The frontend is Next.js + React in JavaScript/JSX only (ADR 0006)."""

import json
import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
SKIP = {"node_modules", ".next", ".next-preview", "out"}  # build output (.next-preview: a second preview server's)


def frontend_files() -> list[Path]:
    return [
        p
        for p in FRONTEND.rglob("*")
        if p.is_file() and not SKIP & set(p.relative_to(FRONTEND).parts)
    ]


def test_no_typescript_source_or_configuration() -> None:
    bad = [
        str(p.relative_to(FRONTEND))
        for p in frontend_files()
        if p.suffix in {".ts", ".tsx", ".mts", ".cts"}
        or p.name.startswith(("tsconfig", "next-env"))
        or p.name.startswith("vite.config")
    ]
    assert bad == []


def test_no_typescript_or_vite_dependencies() -> None:
    pkg = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    forbidden = [
        n
        for n in deps
        if n in {"typescript", "vite", "react-router-dom"} or n.startswith(("@types/", "@vitejs/"))
    ]
    assert forbidden == []
    assert {"next", "react", "react-dom"} <= set(deps)
    scripts = " ".join(pkg["scripts"].values())
    assert "tsc" not in scripts and "vite" not in scripts


def test_next_app_router_and_loopback_only_frontend() -> None:
    pkg = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    for name in ("dev", "start"):
        assert "-H 127.0.0.1" in pkg["scripts"][name]
    config = (FRONTEND / "next.config.mjs").read_text(encoding="utf-8")
    assert "/api/:path*" in config and "127.0.0.1:8787" in config
    for route in (
        "articles",
        "articles/[id]",
        "topics",
        "publishing",
        "analytics",
        "automation",
        "shipping",
        "settings/integrations",
        "settings/brands",
        "settings/data",
        "settings/audit",
    ):
        assert (FRONTEND / "src" / "app" / route / "page.jsx").is_file(), route
    assert (FRONTEND / "src" / "app" / "page.jsx").is_file()  # Home
    assert not (FRONTEND / "src" / "pages").exists()  # no second (Pages Router) router


def test_unfinished_pages_are_not_mounted() -> None:
    app_dir = FRONTEND / "src" / "app"
    mounted = "\n".join(p.read_text(encoding="utf-8") for p in app_dir.rglob("page.jsx"))
    for unfinished in ("Login", "Planned"):
        assert f"views/{unfinished}'" not in mounted
    # The read-only views/Users.jsx was replaced by Settings → Team (views/Team.jsx) on 24 Nov 2026.
    assert not (FRONTEND / "src" / "views" / "Users.jsx").exists()
    assert "views/Team'" in (app_dir / "settings" / "team" / "page.jsx").read_text(encoding="utf-8")
    # /login is the hosted sign-in page (its own page.jsx since 18 Nov 2026), not the unfinished views/Login.jsx
    assert not (app_dir / "users").exists()
    assert "views/Login" not in (app_dir / "login" / "page.jsx").read_text(encoding="utf-8")


def test_no_planned_destinations_in_navigation() -> None:
    nav = (FRONTEND / "src" / "lib" / "routes.js").read_text(encoding="utf-8")
    for path in (
        "/meta",
        "/creative",
        "/landing",
        "/cro",
        "/approvals",
        "/runs",
        "/alerts",
        "/activity",
        "/library",
        "/settings",
        "/merchandising",
        "/users",
    ):
        assert not re.search(rf"['\"]{re.escape(path)}['\"]", nav), path
