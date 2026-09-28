"""Fixed least-privilege role matrix. The database is the authorization source."""

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "USER": frozenset(),
    "SUPPORT": frozenset({"users:read", "products:read"}),
    "REVIEWER": frozenset(
        {
            "users:read",
            "products:read",
            "moderation:review",
            "campus_appeal:read",
            "campus_appeal:review",
        }
    ),
    "ADMIN": frozenset(
        {
            "users:read",
            "users:status",
            "products:read",
            "products:manage",
            "moderation:review",
            "moderation:suspend",
            "campus_appeal:read",
            "campus_appeal:review",
            "catalog:read",
            "catalog:write",
            "dashboard:read",
            "audit:read",
        }
    ),
    "SUPER_ADMIN": frozenset(
        {
            "users:read",
            "users:status",
            "products:read",
            "products:manage",
            "moderation:review",
            "moderation:suspend",
            "campus_appeal:read",
            "campus_appeal:review",
            "catalog:read",
            "catalog:write",
            "dashboard:read",
            "audit:read",
            "audit:export",
            "staff:manage",
        }
    ),
}

STAFF_ROLES = frozenset({"SUPPORT", "REVIEWER", "ADMIN", "SUPER_ADMIN"})
