from enum import StrEnum


class UserRole(StrEnum):
    OPERATOR = "operator"
    KNOWLEDGE_ADMIN = "knowledge_admin"
    SYSTEM_ADMIN = "system_admin"
    GUEST = "guest"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
