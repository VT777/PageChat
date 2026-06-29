from pydantic import BaseModel, validator
from typing import Optional, List, Dict, Any
from datetime import datetime


# Document schemas
class DocumentBase(BaseModel):
    name: str
    original_name: str
    file_size: int
    file_type: str


class DocumentCreate(DocumentBase):
    id: str
    file_path: str


# Folder schemas
class FolderBase(BaseModel):
    name: str


class FolderCreate(FolderBase):
    parent_id: Optional[str] = None  # null 表示根目录

    @validator("name")
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("文件夹名称不能为空")
        if len(v) > 255:
            raise ValueError("文件夹名称不能超过255个字符")
        if "/" in v or "\\" in v or "\x00" in v:
            raise ValueError("文件夹名称不能包含 /, \\ 或空字符")
        # Check for reserved names (Windows)
        reserved = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "COM2",
            "COM3",
            "COM4",
            "COM5",
            "COM6",
            "COM7",
            "COM8",
            "COM9",
            "LPT1",
            "LPT2",
            "LPT3",
            "LPT4",
            "LPT5",
            "LPT6",
            "LPT7",
            "LPT8",
            "LPT9",
        }
        if v.upper() in reserved:
            raise ValueError(f'"{v}" 是保留名称，不能使用')
        return v.strip()


class FolderResponse(FolderBase):
    id: str
    parent_id: Optional[str] = None
    path: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FolderTreeResponse(FolderResponse):
    children: List["FolderTreeResponse"] = []


class FolderListResponse(BaseModel):
    items: List[FolderResponse]
    total: int


class DocumentResponse(DocumentBase):
    id: str
    file_path: str
    index_path: Optional[str] = None
    status: str
    page_count: Optional[int] = None
    processed_pages: Optional[int] = None
    folder_id: Optional[str] = None
    folder_path: Optional[str] = None
    error_message: Optional[str] = None
    description: Optional[str] = None
    parse_requested_mode: Optional[str] = None
    parse_execution_mode: Optional[str] = None
    parse_reasons: Optional[List[str]] = None
    parse_completion: Optional[str] = None
    parse_error_code: Optional[str] = None
    quality_report: Optional[Dict[str, Any]] = None
    processing_duration: Optional[float] = None
    last_reindex_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    items: List[DocumentResponse]
    total: int


# Processing steps schemas
class ProcessingStep(BaseModel):
    step_type: str
    title: str
    description: str
    status: str  # "pending", "running", "completed", "failed"
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    details: Optional[dict] = None


class ProcessingStepsResponse(BaseModel):
    doc_id: str
    doc_name: str
    status: str
    total_duration_seconds: Optional[float] = None
    steps: List[ProcessingStep]
    current_step: Optional[str] = None


# Chat schemas
class ChatRequest(BaseModel):
    question: str
    document_ids: Optional[List[str]] = None
    attachment_ids: Optional[List[str]] = None
    folder_id: Optional[str] = None
    include_subfolders: bool = False
    strict_scope: Optional[bool] = None
    web_search_requested: bool = False
    web_search_enabled: bool = False
    thinking_enabled: Optional[bool] = None
    conversation_id: Optional[str] = None
    regenerate_from_message_id: Optional[str] = None
    web_search: bool = False


class SourceInfo(BaseModel):
    document_id: str
    document_name: str
    page: int
    excerpt: str
    node_title: Optional[str] = None


class AgentStep(BaseModel):
    step_type: str  # "thinking", "planning", "searching", "analyzing", "generating"
    title: str
    content: str
    status: str  # "pending", "running", "completed"
    details: Optional[dict] = None


class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceInfo] = []
    agent_steps: List[AgentStep] = []
    conversation_id: str


# SSE Event types
class SSEEvent(BaseModel):
    event: str  # "step", "content", "source", "done", "error"
    data: dict
