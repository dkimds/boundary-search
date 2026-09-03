"""biome evidence (브리프 §7 #2).

두 가지 모드를 지원한다.

1. 절대 개수 모드 (parent_repo_path=None, 기본): 변경 파일의 현재 biome lint
   error 개수를 그대로 findings로 만든다. mcp_server/preflight_check가 쓰는
   모드 -- 변경 파일이 "지금 이 상태로" lint를 통과하는지만 본다. umami HEAD
   자체에 baseline 에러 6개가 있지만(docs/findings.md Phase 0 실측), 이 모드는
   그 파일들이 실제로 변경 파일에 포함될 때만 걸리므로 실사용(현재 작업 트리
   검사)에서는 문제가 되지 않는다. 임의 레포에서 baseline이 크면 오판 가능성이
   있음을 인지하고 쓴다.
2. 부모 비교 모드 (parent_repo_path 지정): "변경 파일 한정 + 부모 커밋 대비
   신규 에러 수"로 판정한다 (decisions.md 2026-09-03 "biome evidence 정의").
   Phase 2/3 실험(보류 중)에서 umami 레포 baseline 오판을 피하려고 만든 모드.
   재개 시 그대로 재사용한다.

biome check가 아니라 biome lint만 쓰고, warning은 무시하고 error만 센다
(§8 "biome은 warning이 아니라 error만 본다").

LLM 호출 없음 (스펙 §13-1).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections import Counter

from boundary.schemas import EvidenceResult, EvidenceStatus

TIMEOUT_S = 600  # SS13-4: evidence 하나당 타임아웃 10분


def _lint_error_counts(repo_path: str, files: list[str]) -> dict[str, int] | None:
    """repo_path 기준 존재하는 files만 biome lint 돌려 파일별 error 개수를 센다.

    실행 자체가 실패하면(타임아웃, biome 크래시 등) None을 반환한다.
    files가 비어있으면 빈 dict를 반환한다 (린트할 게 없음, 실패 아님).
    """
    existing = [f for f in files if os.path.isfile(os.path.join(repo_path, f))]
    if not existing:
        return {}

    try:
        proc = subprocess.run(
            ["npx", "biome", "lint", "--reporter=json", *existing],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return None

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None

    counts: Counter[str] = Counter()
    for diag in payload.get("diagnostics", []):
        if diag.get("severity") != "error":
            continue
        path = diag.get("location", {}).get("path")
        if path:
            counts[path] += 1
    return dict(counts)


def _run_absolute(repo_path: str, ts_files: list[str], started: float) -> EvidenceResult:
    counts = _lint_error_counts(repo_path, ts_files)
    duration = time.monotonic() - started
    if counts is None:
        return EvidenceResult(
            status=EvidenceStatus.FAILED,
            duration_s=duration,
            summary="biome lint failed",
            extra={},
        )

    errors = [
        {"file": f, "detail": f"{n} error(s)"}
        for f, n in sorted(counts.items())
        if n > 0
    ]
    total = sum(counts.values())
    return EvidenceResult(
        status=EvidenceStatus.COMPLETE,
        duration_s=duration,
        summary=f"{total} errors",
        extra={"errors": errors},
    )


def _run_parent_diff(
    repo_path: str, parent_repo_path: str, ts_files: list[str], started: float
) -> EvidenceResult:
    child_counts = _lint_error_counts(repo_path, ts_files)
    if child_counts is None:
        duration = time.monotonic() - started
        return EvidenceResult(
            status=EvidenceStatus.FAILED,
            duration_s=duration,
            summary="biome lint failed on child worktree",
            extra={},
        )

    parent_counts = _lint_error_counts(parent_repo_path, ts_files)
    if parent_counts is None:
        duration = time.monotonic() - started
        return EvidenceResult(
            status=EvidenceStatus.FAILED,
            duration_s=duration,
            summary="biome lint failed on parent worktree",
            extra={},
        )

    errors = []
    new_error_total = 0
    for f in ts_files:
        child_n = child_counts.get(f, 0)
        parent_n = parent_counts.get(f, 0)  # 신규 파일은 parent 0으로 취급
        new_n = max(0, child_n - parent_n)
        new_error_total += new_n
        if new_n > 0:
            errors.append(
                {
                    "file": f,
                    "detail": f"{new_n} new error(s) (child={child_n}, parent={parent_n})",
                }
            )

    duration = time.monotonic() - started
    return EvidenceResult(
        status=EvidenceStatus.COMPLETE,
        duration_s=duration,
        summary=f"{new_error_total} new errors",
        extra={"errors": errors},
    )


def run(repo_path: str, changed_files: list[str], parent_repo_path: str | None = None) -> EvidenceResult:
    started = time.monotonic()
    ts_files = [f for f in changed_files if f.endswith(".ts") or f.endswith(".tsx")]
    if parent_repo_path is None:
        return _run_absolute(repo_path, ts_files, started)
    return _run_parent_diff(repo_path, parent_repo_path, ts_files, started)
