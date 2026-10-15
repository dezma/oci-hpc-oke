from __future__ import annotations

import ipaddress
import re
from typing import Literal
from pydantic import BaseModel, Field, field_validator

Action = Literal[
    "preflight",
    "configure_vfs",
    "configure_network",
    "rdma_validation",
    "cleanup_validation",
]


class JobCreate(BaseModel):
    action: Action
    confirmation: str = Field(default="", max_length=128)


class LoginCheck(BaseModel):
    ok: bool = True


class RdmaConfigUpdate(BaseModel):
    rdma_pf_name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    rdma_mtu: int = Field(ge=1500, le=9700)
    rdma_vfs_per_node: int = Field(ge=1, le=16)
    rdma_resource_name: str = Field(min_length=1, max_length=63, pattern=r"^[a-z0-9_]+$")
    rdma_ip_pool_cidr: str = Field(min_length=9, max_length=64)
    rdma_tools_image: str = Field(default="", max_length=512)

    @field_validator("rdma_ip_pool_cidr")
    @classmethod
    def validate_cidr(cls, value: str) -> str:
        network = ipaddress.ip_network(value, strict=False)
        if network.version != 4:
            raise ValueError("The current NVIDIA IPAM workflow requires an IPv4 pool")
        if network.prefixlen > 28:
            raise ValueError("Use an IPv4 pool of /28 or larger so validation/workload VFs have usable addresses")
        return str(network)

    @field_validator("rdma_tools_image")
    @classmethod
    def validate_image(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        if not re.fullmatch(r"[^\s@]+@sha256:[0-9a-fA-F]{64}", value):
            raise ValueError("Use an immutable container reference in repository@sha256:<64-hex-digest> form")
        return value
