"""DRF permission classes backed by the role matrix in roles.py."""
from __future__ import annotations

from rest_framework.permissions import BasePermission


class HasPerm(BasePermission):
    """`permission_classes = [HasPerm.of("assets.manage")]`."""

    required: tuple[str, ...] = ()

    @classmethod
    def of(cls, *codes: str) -> type["HasPerm"]:
        return type(f"HasPerm_{'_'.join(c.replace('.', '_') for c in codes)}", (cls,), {"required": codes})

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and all(user.has_perm_code(c) for c in self.required))


class ActionPermission(BasePermission):
    """Looks up `view.action_permissions[action]` (falls back to the `'*'` key).

    Read actions default to `view.read_permission`. A missing entry denies the request,
    so new actions are closed by default.
    """

    READ_ACTIONS = {"list", "retrieve", "metadata"}

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        action = getattr(view, "action", None) or request.method.lower()
        mapping: dict = getattr(view, "action_permissions", {})
        code = mapping.get(action)
        if code is None and action in self.READ_ACTIONS:
            code = getattr(view, "read_permission", None)
        if code is None:
            code = mapping.get("*")
        if code is None:
            return False
        codes = (code,) if isinstance(code, str) else tuple(code)
        # A tuple means "any of these permissions".
        return any(user.has_perm_code(c) for c in codes)
