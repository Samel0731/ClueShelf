"""Public result and evidence types for YouTube analysis."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VideoMode = Literal["text", "transcribe"]
SourceKind = Literal["description", "chapter", "comment", "caption", "transcript"]


class VideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: VideoMode
    audio_authorized: bool = False


class Evidence(BaseModel):
    source: SourceKind
    quote: str
    start_seconds: float | None


class Finding(BaseModel):
    kind: Literal["song", "stock"]
    name: str
    ticker: str | None
    evidence: list[Evidence]


class Coverage(BaseModel):
    source: SourceKind
    segments: int
    through_seconds: float | None


class VideoResult(BaseModel):
    mode: VideoMode
    duration_seconds: float | None
    coverage: list[Coverage]
    warnings: list[str]
    findings: list[Finding]


class VideoProgress(BaseModel):
    stage: Literal["preparing", "downloading", "transcribing", "analyzing"]
    percent: int | None = Field(default=None, ge=0, le=99)


class VideoView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    mode: VideoMode
    state: Literal["queued", "running", "done", "failed"]
    error: str | None
    result: VideoResult | None
    progress: VideoProgress | None = None


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["song", "stock"]
    name: str = Field(min_length=1, max_length=120)
    ticker: str | None = Field(max_length=24)
    segment: int = Field(ge=0)
    quote: str = Field(min_length=1, max_length=350)


class CandidateBatch(BaseModel):
    candidates: list[Candidate] = Field(max_length=100)
