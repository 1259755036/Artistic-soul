from datetime import datetime
from enum import Enum
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RecordStatus(str, Enum):
    VALID = "valid"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"


class ParseRequest(BaseModel):
    text: Optional[str] = None
    texts: Optional[List[str]] = None
    use_llm: bool = False


class ParseResponse(BaseModel):
    records: List[Dict[str, Any]]
    status: RecordStatus
    reasons: List[str] = Field(default_factory=list)
    record_id: Optional[int] = None


class RecordListResponse(BaseModel):
    id: int
    created_at: datetime
    updated_at: datetime
    raw_text: str
    parsed: Dict[str, Any]
    status: RecordStatus
    reasons: List[str]


class ReviewUpdate(BaseModel):
    parsed: Dict[str, Any]
    status: RecordStatus = RecordStatus.APPROVED


class ConfigReloadResponse(BaseModel):
    reloaded: bool
