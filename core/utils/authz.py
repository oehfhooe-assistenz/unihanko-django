# core/authz.py
from __future__ import annotations
import os
from functools import lru_cache
from typing import Set, Dict

import yaml
from django.conf import settings

# Default to BASE_DIR/config/access.yaml but allow override in settings
ACL_PATH = getattr(
    settings,
    "ACL_CONFIG_PATH",
    os.path.join(settings.BASE_DIR, "config", "access.yaml"),
)

@lru_cache(maxsize=1)
def _load_acl() -> Dict[str, Set[str]]:
    """
    Parse YAML once. On any error, return empty sets (fail-closed).
    Structure returned: {"groups": {<group names>}}
    """
    try:
        with open(ACL_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        groups = set((data.get("groups") or {}).keys())
        return {"groups": groups}
    except Exception:
        return {"groups": set()}

def _group_in_acl(name: str) -> bool:
    groups = _load_acl()["groups"]
    # If ACL file has no groups at all, fail-closed.
    return bool(groups) and name in groups

def is_in_group(user, group_name: str) -> bool:
    """
    True iff user is in the Django group *and* that group is declared in access.yaml.
    If the group isn’t declared (or ACL missing), we return False.
    """
    if not (user and user.is_authenticated):
        return False
    if not _group_in_acl(group_name):
        return False
    # DB check only if ACL says this group exists
    return user.groups.filter(name=group_name).exists()

def is_module_manager(user, module_code: str) -> bool:
    """
    Example: is_module_manager(user, "personnel") -> checks "module:personnel:manager"
    """
    return is_in_group(user, f"module:{module_code}:manager")

# Nice shortcuts
def is_people_manager(user) -> bool:
    return is_module_manager(user, "personnel")

def is_finances_manager(user) -> bool:
    return is_module_manager(user, "finances")

def is_employees_manager(user) -> bool:
    return is_module_manager(user, "employees")

# ADD this function:

def is_assembly_manager(user) -> bool:
    return is_module_manager(user, "assembly")

def refresh_acl_cache() -> None:
    """Call this if you change access.yaml at runtime (e.g., from a management command)."""
    _load_acl.cache_clear()
