"""tsc evidence (브리프 §7 #1).

두 가지 모드를 지원한다.

1. 절대 개수 모드 (parent_repo_path=None, 기본): repo_path에서 tsc --noEmit을
   돌려 나온 에러 개수를 그대로 findings로 만든다. mcp_server/preflight_check가
   쓰는 모드 -- worktree나 커밋 이력 없이 "지금 이 작업 트리"를 그대로 검사한다.
2. 부모 비교 모드 (parent_repo_path 지정): "부모 커밋 대비 신규 타입 에러 수"로
   판정한다. Phase 2/3 실험(보류 중)에서 쓰던 모드. umami 과거 커밋 다수가 그
   시점 기준으로도 이미 타입 에러를 갖고 있어 절대 개수로는 오판이 났기 때문에
   만들어졌다 (decisions.md 2026-09-03 "tsc evidence: 절대 개수 -> 부모 대비
   신규 개수로 통일" 참고). Phase 2/3 재개 시 그대로 재사용한다.

parent_repo_path가 주어졌는데 비교 자체가 실패하면(worktree 문제 등)
status=FAILED로 반환해 policy가 INDETERMINATE로 처리하게 한다.

LLM 호출 없음 (스펙 §13-1).
"""

from __future__ import annotations

import re
import subprocess
import time
from collections import Counter

from boundary.schemas import EvidenceResult, EvidenceStatus

TIMEOUT_S = 600  # SS13-4: evidence 하나당 타임아웃 10분

_ERROR_LINE = re.compile(r"^(?P<file>[^\s(][^(]*)\((?P<line>\d+),(?P<col>\d+)\): error (?P<code>TS\d+): (?P<message>.*)$")


def _tsc_errors(repo_path: str) -> list[dict] | None:
    """repo_path에서 tsc --noEmit을 돌려 에러 목록을 반환한다.

    tsc 실행 자체가 실패하면(타임아웃, 파싱 불가한 비정상 종료) None을 반환한다.
    """
    try:
        proc = subprocess.run(
            ["npx", "tsc", "--noEmit", "-p", "tsconfig.json"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return None

    output = proc.stdout + proc.stderr
    errors = []
    for line in output.splitlines():
        m = _ERROR_LINE.match(line.strip())
        if m:
            errors.append(
                {
                    "file": m.group("file"),
                    "line": int(m.group("line")),
                    "column": int(m.group("col")),
                    "code": m.group("code"),
                    "detail": m.group("message"),
                }
            )

    # 에러가 있으면 exit code != 0. 에러 파싱이 0건인데 exit code가 비정상이면
    # (컴파일러 자체 크래시, 설정 오류 등) 판정 불가로 처리한다.
    if proc.returncode != 0 and not errors:
        return None

    return errors


def _run_absolute(repo_path: str, started: float) -> EvidenceResult:
    errors = _tsc_errors(repo_path)
    duration = time.monotonic() - started
    if errors is None:
        return EvidenceResult(
            status=EvidenceStatus.FAILED,
            duration_s=duration,
            summary="tsc failed",
            extra={},
        )
    return EvidenceResult(
        status=EvidenceStatus.COMPLETE,
        duration_s=duration,
        summary=f"{len(errors)} errors",
        extra={"errors": errors},
    )


def _run_parent_diff(repo_path: str, parent_repo_path: str, started: float) -> EvidenceResult:
    child_errors = _tsc_errors(repo_path)
    if child_errors is None:
        duration = time.monotonic() - started
        return EvidenceResult(
            status=EvidenceStatus.FAILED,
            duration_s=duration,
            summary="tsc failed on child worktree",
            extra={},
        )

    parent_errors = _tsc_errors(parent_repo_path)
    if parent_errors is None:
        duration = time.monotonic() - started
        return EvidenceResult(
            status=EvidenceStatus.FAILED,
            duration_s=duration,
            summary="tsc failed on parent worktree",
            extra={},
        )

    child_counts = Counter(e["file"] for e in child_errors)
    parent_counts = Counter(e["file"] for e in parent_errors)

    all_files = set(child_counts) | set(parent_counts)
    new_error_total = 0
    new_errors = []
    for f in all_files:
        child_n = child_counts.get(f, 0)
        parent_n = parent_counts.get(f, 0)  # parent에 없던 파일은 parent 0으로 취급
        new_n = max(0, child_n - parent_n)
        new_error_total += new_n
        if new_n > 0:
            new_errors.append(
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
        extra={"errors": sorted(new_errors, key=lambda e: e["file"])},
    )


def run(repo_path: str, changed_files: list[str], parent_repo_path: str | None = None) -> EvidenceResult:
    started = time.monotonic()
    if parent_repo_path is None:
        return _run_absolute(repo_path, started)
    return _run_parent_diff(repo_path, parent_repo_path, started)
