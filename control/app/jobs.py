from __future__ import annotations

from typing import Any
from .config import Settings
from .provider import get_provider

MUTATING = {"configure_vfs", "configure_network", "cleanup_validation"}


def validate_request(settings: Settings, action: str, confirmation: str) -> None:
    if action in MUTATING and confirmation != settings.environment_name:
        raise ValueError(f"Type the exact environment name '{settings.environment_name}' to approve this change")


def execute(settings: Settings, action: str) -> dict[str, Any]:
    provider = get_provider(settings)
    if action == "preflight":
        return provider.preflight()
    if action == "configure_vfs":
        return provider.configure_vfs()
    if action == "configure_network":
        return provider.configure_network()
    if action == "rdma_validation":
        return provider.rdma_validation()
    if action == "cleanup_validation":
        return provider.cleanup_validation()
    raise ValueError(f"unsupported action: {action}")
