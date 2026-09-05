"""Explicit, serializable interpretation of the natural-language entry request."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConstructionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    domain: Literal["lifesci", "physics", "chemistry", "mathematics"]
    research_type: str = Field(min_length=1)
    capability: Literal["writing_reconstruction", "proof_discovery"] = "writing_reconstruction"
    topic: str = ""
    source_ids: list[str] = Field(default_factory=list)
    source_scope: Literal["redistributable arXiv papers with versioned LaTeX sources"] = "redistributable arXiv papers with versioned LaTeX sources"
    target_count: int = Field(default=1, ge=1)
    material_policy: Literal["sufficient_public_evidence"] = "sufficient_public_evidence"
    difficulty: Literal["reconstruct scientific writing from supplied evidence"] = "reconstruct scientific writing from supplied evidence"
    timeout_seconds: int = Field(default=5400, ge=1)
    max_turns: int = Field(default=3, ge=1)
    concurrency: int = Field(default=1, ge=1)
    trial_timeout_seconds: int = Field(default=1800, ge=1)
    delivery_root: str = Field(min_length=1)
    upload_candidate: bool = False
    publish: bool = False

    @model_validator(mode="after")
    def supported(self):
        from .knowledge import get_knowledge_package

        get_knowledge_package(self.domain, self.research_type)
        if self.capability == "proof_discovery":
            raise ValueError("proof_discovery is distinct from reconstruction and not supported yet")
        if self.publish and not self.upload_candidate:
            raise ValueError("publish requires separate upload_candidate intent")
        return self
