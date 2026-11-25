"""Role → permission map. Every route checks a permission with require_perm(); the browser gets a
copy only to hide buttons — hiding is a convenience, the server is the gate."""

PERMISSIONS: dict[str, str] = {
    "view": "See dashboards, records and analytics",
    "topic:write": "Create and edit topics and keywords",
    "topic:decide": "Approve or reject topics",
    "article:write": "Create and edit blog content",
    "article:submit": "Send content for review",
    "article:review": "Approve content or request changes",
    "shopify:draft": "Save articles to Shopify as hidden drafts",
    "publish:request": "Ask for an article to be published or scheduled",
    "publish:authorize": "Approve publish requests and make articles live",
    "workflow:run": "Run, retry or pause automation stages",
    "analytics:sync": "Refresh data from connected services",
    "data:import": "Import Excel workbooks",
    "integrations:manage": "Test integrations and change brand settings",
    "users:manage": "Add users and change roles",
    "audit:view": "Read the audit log",
    "demo:manage": "Load or clear demo fixtures",
}

ROLE_PERMS: dict[str, list[str]] = {
    "admin": list(PERMISSIONS),
    "seo_manager": [
        "view", "topic:write", "topic:decide", "article:write", "article:submit", "shopify:draft",
        "publish:request", "workflow:run", "analytics:sync", "data:import", "audit:view",
    ],
    "reviewer": ["view", "article:review", "publish:authorize", "analytics:sync", "audit:view"],
    # Only reachable through Supabase sign-in (identity.py): looks at everything, changes nothing.
    "viewer": ["view"],
}

ROLE_LABELS = {"admin": "Admin", "seo_manager": "SEO Manager", "reviewer": "Reviewer / Approver"}
# The roles a record in the local `users` table may hold (its CHECK constraint). "viewer" is not one of them.
LOCAL_ROLES = tuple(ROLE_LABELS)


def can(role: str, perm: str) -> bool:
    return perm in ROLE_PERMS.get(role, [])


def perms_for(role: str) -> list[str]:
    return ROLE_PERMS.get(role, [])


def is_role(v: object) -> bool:
    return v in LOCAL_ROLES
