from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class SessionCreateRequest(BaseModel):
    title: str = Field(default="新诊断会话", min_length=1, max_length=200)
    device_id: str | None = None


class SessionUpdateRequest(BaseModel):
    device_id: str | None = None


class MessageCreateRequest(BaseModel):
    session_id: str
    text: str = Field(min_length=1, max_length=8000)
    device_id: str | None = None


class KnowledgeTextRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=500_000)
    version: str = Field(default="1", min_length=1, max_length=80)
    device_model: str | None = Field(default=None, max_length=120)
    source_url: str | None = Field(default=None, max_length=500)
    publisher: str | None = Field(default=None, max_length=160)
    license: str | None = Field(default=None, max_length=160)
    document_type: str | None = Field(default=None, max_length=80)
    language: str = Field(default='zh-CN', max_length=20)
    applicability: str | None = Field(default=None, max_length=500)


class UserView(BaseModel):
    id: str
    username: str
    role: str


class SessionView(BaseModel):
    id: str
    title: str
    status: str
    device_id: str | None
    created_at: datetime


class MessageView(BaseModel):
    id: str
    role: str
    text: str | None
    status: str
    citations: list[dict] = []
    stage_states: dict = {}
    created_at: datetime
