"""Strict input schemas. Nothing reaches an upstream service unvalidated."""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import config

# Object names: letters, digits, space and the punctuation real designations use
# (e.g. "C/2025 N1", "3I", "M 51", "NGC 1068", "67P/Churyumov-Gerasimenko").
OBJECT_NAME_RE = re.compile(r"^[A-Za-z0-9 ./+_\-']{1,%d}$" % config.MAX_OBJECT_NAME_LEN)

Mode = Literal["blink", "flicker", "timeline", "difference"]
Stretch = Literal["asinh", "log", "linear"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResolveQuery(StrictModel):
    name: str = Field(min_length=1, max_length=config.MAX_OBJECT_NAME_LEN)

    @field_validator("name")
    @classmethod
    def _charset(cls, v: str) -> str:
        if not OBJECT_NAME_RE.match(v):
            raise ValueError(
                "Object name may contain only letters, digits, spaces and . / + _ - '"
            )
        return v


class SearchQuery(StrictModel):
    ra: float = Field(ge=0.0, le=360.0)
    dec: float = Field(ge=-90.0, le=90.0)
    detector: Optional[str] = None
    collection: Optional[str] = None

    @field_validator("detector")
    @classmethod
    def _detector(cls, v):
        if v is None:
            return v
        v = v.upper()
        if v not in config.DETECTORS:
            raise ValueError(f"detector must be one of {', '.join(config.DETECTORS)}")
        return v

    @field_validator("collection")
    @classmethod
    def _collection(cls, v):
        if v is None:
            return v
        if v not in config.SCIENCE_COLLECTIONS:
            raise ValueError("unknown collection")
        return v


class JobRequest(StrictModel):
    """A blink/difference job. `band` is the 0-101 spectral channel index the UI
    exposes; the backend always re-derives true wavelength per frame."""

    ra: float = Field(ge=0.0, le=360.0)
    dec: float = Field(ge=-90.0, le=90.0)
    size_deg: float = Field(
        default=config.DEFAULT_CUTOUT_SIZE_DEG, gt=0.0, le=config.MAX_CUTOUT_SIZE_DEG
    )
    detector: Optional[str] = None
    band: Optional[int] = Field(default=None, ge=0, le=101)
    wavelength_um: Optional[float] = Field(default=None, gt=0.0, le=6.0)
    tolerance_bandwidths: float = Field(
        default=config.DEFAULT_TOLERANCE_BANDWIDTHS,
        gt=0.0,
        le=config.MAX_TOLERANCE_BANDWIDTHS,
    )
    max_frames: int = Field(default=12, ge=2, le=config.MAX_FRAMES_PER_JOB)
    stretch: Stretch = "asinh"
    color: bool = False
    collection: Optional[str] = None

    _detector = field_validator("detector")(SearchQuery._detector.__func__)
    _collection = field_validator("collection")(SearchQuery._collection.__func__)


class MovingObjectQuery(StrictModel):
    """MOST rejects informal names; see docs/service-findings.md §7."""

    name: str = Field(min_length=1, max_length=config.MAX_OBJECT_NAME_LEN)

    @field_validator("name")
    @classmethod
    def _charset(cls, v: str) -> str:
        if not OBJECT_NAME_RE.match(v):
            raise ValueError("unsupported characters in object name")
        return v


class SpectrumQuery(StrictModel):
    ra: float = Field(ge=0.0, le=360.0)
    dec: float = Field(ge=-90.0, le=90.0)
    size_deg: float = Field(
        default=config.DEFAULT_CUTOUT_SIZE_DEG, gt=0.0, le=config.MAX_CUTOUT_SIZE_DEG
    )
    max_frames: int = Field(default=18, ge=2, le=config.MAX_FRAMES_PER_JOB)
