"""MCP 서버: preflight_check 툴 하나만 노출한다 (브리프 §10 Phase 4).

config는 tsc + biome + import_graph_impact로 고정한다 (스펙에 config 선택
기능은 없으므로 추가하지 않음). Phase 2/3(과거 커밋 전수 실험)에서 쓰던
worktree/lockfile 캐시/부모 커밋 비교 경로는 쓰지 않는다 -- 현재 작업 트리를
현재 node_modules로 그대로 검사한다.

LLM 호출 없음 (스펙 §13-1). evidence/policy 모듈을 그대로 재사용하고 이 파일은
MCP 트랜스포트 배선과 changed_files 자동 판단만 담당한다.
"""

from __future__ import annotations

import argparse
import datetime
import subprocess
import time

from mcp.server.fastmcp import FastMCP

from boundary.evidence import biome, import_graph_impact, tsc
from boundary.policy import evaluate
from boundary.schemas import CheckedResult, RunMeta

CONFIG_ID = "tsc+biome+import_graph_impact"

mcp = FastMCP("boundary-search-preflight")


def _git_changed_files(repo_path: str) -> list[str]:
    """git diff로 현재 작업 트리의 변경 파일을 스스로 판단한다.

    HEAD 대비 수정/추가/삭제된 파일(staged+unstaged) + untracked 파일을 합쳐
    src/**/*.ts 또는 .tsx만 남긴다. 삭제된 파일은 diff --name-only에 잡히지만
    존재하지 않으므로 evidence 쪽에서 os.path.isfile로 자연히 걸러진다.
    """
    tracked = subprocess.run(
        ["git", "-C", repo_path, "diff", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.splitlines()
    untracked = subprocess.run(
        ["git", "-C", repo_path, "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.splitlines()

    files = sorted(set(tracked) | set(untracked))
    return [f for f in files if f.startswith("src/") and (f.endswith(".ts") or f.endswith(".tsx"))]


def _current_commit(repo_path: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.stdout.strip() or "unknown"


@mcp.tool()
def preflight_check(repo_path: str, changed_files: list[str] | None = None) -> dict:
    """배포 전 변경 사항이 안전한지 판정한다 (§6 checked result 스키마 반환).

    changed_files를 생략하면 repo_path의 현재 git 작업 트리 변경분을 스스로
    판단한다 (HEAD 대비 diff + untracked, src/**/*.ts|tsx만).
    config는 tsc + biome + import_graph_impact로 고정이며 부모 커밋 비교 없이
    현재 상태만 검사한다 (parent_repo_path=None, 절대 개수 모드).
    """
    started = time.monotonic()
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if changed_files is None:
        changed_files = _git_changed_files(repo_path)

    tsc_result = tsc.run(repo_path, changed_files)
    biome_result = biome.run(repo_path, changed_files)
    igi_result = import_graph_impact.run(repo_path, changed_files)

    evidence = {
        "tsc": tsc_result,
        "biome": biome_result,
        "import_graph_impact": igi_result,
    }

    outcome, findings, actions = evaluate(evidence)

    total_duration = time.monotonic() - started
    commit = _current_commit(repo_path)
    result = CheckedResult(
        outcome=outcome,
        config_id=CONFIG_ID,
        change_sha=commit,
        evidence=evidence,
        findings=findings,
        actions=actions,
        total_duration_s=round(total_duration, 3),
        run_meta=RunMeta(commit=commit, started_at=started_at),
    )
    return result.model_dump_json_schema6()


def main() -> None:
    parser = argparse.ArgumentParser(description="boundary-search preflight MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport (default: stdio, for Claude Code / Cursor)",
    )
    args = parser.parse_args()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
