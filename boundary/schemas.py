"""Pydantic 스키마. 브리프 §6 Checked result 스키마를 그대로 구현한다.

이 모듈에는 LLM 호출이 없다 (스펙 §13-1).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class EvidenceStatus(str, Enum):
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class Outcome(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    INDETERMINATE = "INDETERMINATE"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class EvidenceResult(BaseModel):
    """단일 evidence 모듈 실행 결과. §6의 evidence.<id> 항목과 1:1 대응."""

    status: EvidenceStatus
    duration_s: float
    summary: str
    # evidence별 부가 정보 (예: import_graph_impact.routes). 상위 스키마에 새 필드를
    # 추가하지 않고 여기 담아 §6 예시의 "routes": [...] 형태를 그대로 지원한다.
    extra: dict[str, Any] = Field(default_factory=dict)

    def model_dump_evidence(self) -> dict[str, Any]:
        """§6 예시처럼 extra 필드를 최상위로 펼쳐서 직렬화."""
        data = self.model_dump(exclude={"extra"})
        data.update(self.extra)
        return data


class Finding(BaseModel):
    code: str
    severity: Severity
    file: Optional[str] = None
    route: Optional[str] = None
    routes: Optional[list[str]] = None
    detail: str


class Action(BaseModel):
    type: str
    executable: bool
    approval_required: bool


class RunMeta(BaseModel):
    commit: str
    started_at: str


class CheckedResult(BaseModel):
    outcome: Outcome
    config_id: str
    change_sha: str
    evidence: dict[str, EvidenceResult]
    findings: list[Finding] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    total_duration_s: float
    run_meta: RunMeta

    def model_dump_json_schema6(self) -> dict[str, Any]:
        """§6 스키마 형태(evidence.extra를 펼친 형태)로 직렬화."""
        data = self.model_dump(mode="json", exclude={"evidence"})
        data["evidence"] = {k: v.model_dump_evidence() for k, v in self.evidence.items()}
        return data
