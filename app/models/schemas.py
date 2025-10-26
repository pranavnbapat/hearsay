# app/models/schemas.py

from typing import Optional, List

from pydantic import BaseModel, Field


class Segment(BaseModel):
    start: float
    end: float
    text: str

class TranscriptionResponse(BaseModel):
    source: str = Field(..., description="upload|youtube")
    detected_language: str
    duration_sec: Optional[float] = None
    transcript_original: str
    transcript_english: str
    segments: Optional[List[Segment]] = None
    translation_status: Optional[str] = Field(None, description="ok|failed")

