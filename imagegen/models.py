"""Small data contracts aligned with blueprint sections 8.1 and 8.2."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Asset:
    asset_id: str
    type: str
    uri: str
    mime_type: str
    provider: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ImageGenerationJob:
    job_id: str
    workflow_id: str
    provider: str
    provider_job_id: str | None
    prompt: str
    user_prompt: str
    final_prompt: str
    reference_asset_ids: list[str]
    product_asset_ids: list[str]
    brand_reference_asset_ids: list[str]
    reference_files_used: list[dict[str, str]]
    parameters: dict[str, Any]
    status: str
    output_asset_ids: list[str]
    output_asset_paths: list[str]
    output_assets: list[dict[str, Any]]
    error: dict[str, str] | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

