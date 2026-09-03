"""import_graph_impact evidence (브리프 §7 #3).

madge로 src/ 전체의 정적 import 그래프를 얻고, 변경 파일을 역방향으로 BFS해
어떤 src/app/**/page.tsx 에 도달하는지 찾는다. 도달한 page.tsx를 route 경로로
변환해 반환한다. route group 변환 규칙은 decisions.md 2026-09-03
"import_graph_impact: route group 변환 규칙" 참고.

구현 메모: madge(Node.js)를 subprocess 파이프로 직접 캡처하면 macOS 파이프
버퍼(64KB)를 넘는 출력이 flush 전에 잘리는 Node.js 알려진 버그가 실측으로
확인됐다 (파이프 캡처 시 65536바이트에서 끊김, 파일로 직접 쓰면 211072바이트
전체가 정상 기록됨). 그래서 stdout을 파이프가 아니라 임시 파일로 리다이렉트해
읽는다.

LLM 호출 없음 (스펙 §13-1).
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from collections import defaultdict, deque
from pathlib import Path

from boundary.schemas import EvidenceResult, EvidenceStatus

TIMEOUT_S = 600  # SS13-4: evidence 하나당 타임아웃 10분

_ROUTE_GROUP = re.compile(r"^\([^/]*\)$")


def _to_route(page_path: str) -> str:
    """madge 키(src 기준 상대경로, 예: app/(main)/websites/[id]/page.tsx)를
    URL route로 변환한다."""
    parts = page_path.split("/")
    if parts and parts[0] == "app":
        parts = parts[1:]
    if parts and parts[-1] in ("page.tsx", "page.ts", "route.ts", "route.tsx"):
        parts = parts[:-1]
    kept = [p for p in parts if not _ROUTE_GROUP.match(p)]
    route = "/" + "/".join(kept)
    return route if route != "//" else "/"


def _run_madge(repo_path: str) -> dict[str, list[str]] | None:
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "madge_out.json"
        try:
            with open(out_path, "wb") as out_file:
                proc = subprocess.run(
                    [
                        "npx",
                        "madge",
                        "--ts-config",
                        "tsconfig.json",
                        "--extensions",
                        "ts,tsx",
                        "--json",
                        "src",
                    ],
                    cwd=repo_path,
                    stdout=out_file,
                    stderr=subprocess.DEVNULL,
                    timeout=TIMEOUT_S,
                )
        except subprocess.TimeoutExpired:
            return None

        if proc.returncode != 0:
            return None

        try:
            return json.loads(out_path.read_text())
        except json.JSONDecodeError:
            return None


def _normalize(changed_file: str) -> str:
    """changed_files는 'src/app/.../X.tsx' 형태(레포 루트 기준). madge 키는
    'src' 기준 상대경로이므로 'src/' 접두어를 제거한다."""
    if changed_file.startswith("src/"):
        return changed_file[len("src/") :]
    return changed_file


def run(repo_path: str, changed_files: list[str], parent_repo_path: str | None = None) -> EvidenceResult:
    started = time.monotonic()

    graph = _run_madge(repo_path)
    if graph is None:
        duration = time.monotonic() - started
        return EvidenceResult(
            status=EvidenceStatus.FAILED,
            duration_s=duration,
            summary="madge failed or timed out",
            extra={},
        )

    # 역방향 그래프: dep -> [importer, ...]
    reverse: dict[str, list[str]] = defaultdict(list)
    for importer, deps in graph.items():
        for dep in deps:
            reverse[dep].append(importer)

    src_changed = [_normalize(f) for f in changed_files]
    src_changed = [f for f in src_changed if f in graph or f in reverse]

    visited: set[str] = set()
    queue: deque[str] = deque(src_changed)
    visited.update(src_changed)
    pages: set[str] = set()

    while queue:
        node = queue.popleft()
        if node.startswith("app/") and node.split("/")[-1] in ("page.tsx", "page.ts"):
            pages.add(node)
        for importer in reverse.get(node, []):
            if importer not in visited:
                visited.add(importer)
                queue.append(importer)

    routes = sorted({_to_route(p) for p in pages})

    duration = time.monotonic() - started
    return EvidenceResult(
        status=EvidenceStatus.COMPLETE,
        duration_s=duration,
        summary=f"{len(routes)} routes affected",
        extra={"routes": routes},
    )
