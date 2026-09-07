from enum import StrEnum


class UserRole(StrEnum):
    OPERATOR = "operator"
    MAINTENANCE_SUPERVISOR = "maintenance_supervisor"
    KNOWLEDGE_ADMIN = "knowledge_admin"
    SYSTEM_ADMIN = "system_admin"
    GUEST = "guest"

class FaultStatus(StrEnum):
    NEW = "new"
    CONFIRMED = "confirmed"
    IN_PROGRESS = "in_progress"
    PENDING_VERIFICATION = "pending_verification"
    CLOSED = "closed"

class KnowledgeStatus(StrEnum):
    UPLOADED = "uploaded"
    INDEXING = "indexing"
    INDEXED = "indexed"
    PUBLISHED = "published"
    RETIRED = "retired"
    FAILED = "failed"


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
