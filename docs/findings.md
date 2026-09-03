# Findings

## Phase 0 실측 (2026-09-03)

환경: macOS, pnpm, target/umami @ origin/dev
데이터셋: data/changes.jsonl — n=481, BROKE 119 (24.7%), 고빈도 파일 56개 제외

| evidence | 결과 | 소요 |
|---|---|---|
| `tsc --noEmit` | 에러 0 | 23.3초 |
| `biome lint src` | 에러 6 (baseline) | 0.28초 |
| `biome check src` | 에러 106 — 포맷/import 정렬 포함, evidence 미사용 | 2.6초 |

- biome이 tsc의 약 1/80 비용. 파레토 프론티어에서 항상 포함되는 쪽으로 나올 것으로 예상.
- 실제 트레이드오프는 route_build / unit_test 포함 여부에서 갈릴 것.
- 시간 예산: tsc 23초 × 481 커밋 × tsc 포함 config 4개 ≈ 12시간(순차). sweep은 병렬 전제.

## Phase 1 evidence 구현 검증 (2026-09-03)

구현: boundary/evidence/{tsc,biome,import_graph_impact}.py, boundary/policy.py,
boundary/schemas.py. 임의 커밋(HEAD, HEAD~1)과 인위적 에러 주입으로 3개 evidence
모두 실동작 확인.

| evidence | 검증 시나리오 | 결과 |
|---|---|---|
| tsc | HEAD 클린 상태 | COMPLETE, 0 errors, 21.0초 |
| tsc | 2개 파일에 타입 에러 인위 주입 | COMPLETE, 2 errors, 파일/라인/코드 정확히 파싱 |
| biome | parent_repo_path=None | FAILED, "parent worktree unavailable" |
| biome | child==parent(자기 자신 비교), baseline 에러 포함 파일 | COMPLETE, 0 new errors (baseline 상쇄 확인) |
| biome | child에 debugger 문 주입, parent는 원본 | COMPLETE, 1 new error (child=1, parent=0) |
| import_graph_impact | 공용 컴포넌트(LookupField.tsx) 변경 | COMPLETE, 58/60 routes affected, 4.0초 |
| import_graph_impact | 단일 page 전용 파일(AdminSecurityPage.tsx) 변경 | COMPLETE, 1 route (/admin/security) |
| import_graph_impact | 변경 파일 자체가 page.tsx | COMPLETE, 해당 route 1개만 반환 |
| import_graph_impact | 그래프에 없는 무관 파일 | COMPLETE, 0 routes |

**버그 발견**: madge(Node.js) 프로세스를 Python subprocess로 파이프 캡처하면
macOS 파이프 버퍼(64KB)를 넘는 stdout이 65536바이트에서 잘림 (Node.js가
flush 전에 exit하는 문제로 추정). umami src 전체 그래프 JSON은 211072바이트라
실사용 시 항상 잘렸을 것. 임시 파일로 리다이렉트해 읽는 방식으로 우회
(boundary/evidence/import_graph_impact.py 참고). tsc/biome은 출력이 작아
영향 없었음 — 하지만 대규모 tsc 에러 커밋에서도 같은 문제가 재현될 수 있어
Phase 2 러너 구현 시 재확인 필요.

**미측정**: biome/import_graph_impact의 481개 커밋 전체 평균 소요시간. Phase 2
sweep에서 실측 예정.

## Phase 1 심화 검증: node_modules 심볼릭 링크 문제 및 lockfile 캐시 전환 (2026-09-03)

10개 임의 커밋(worktree + parent worktree, node_modules는 HEAD 심볼릭 링크)으로
3개 evidence를 실제 라벨과 대조 검증하던 중 tsc에서 이상 패턴 발견: OK 라벨
8/10건이 정확히 "1 errors"로 동일. 조사 결과 코드 문제가 아니라
tsconfig.json의 baseUrl 옵션(2026-04-15 커밋 7b8403c0에서 제거)이 고정 설치된
TypeScript 6.0.3에서 TS5101(deprecated) 에러로 잡히는 것이었음.

481개 커밋 중 323건(67.2%)이 baseUrl 제거 이전 시점 → 이 방식으로는 tsc evidence
전체가 오염됨이 확인됨.

1차 대응으로 --ignoreDeprecations "6.0" 플래그를 시도했으나, 플래그 적용 후
before 커밋 3건(5d1f2a6f, f7ca5834, 600a3d28)의 에러가 1개→126개로 급증.
원인을 추적한 결과 더 근본적인 문제 발견: node_modules를 HEAD 기준으로 고정
심볼릭 링크하다 보니 2025-08-21 시점 package.json이 요구하는
@umami/react-zen@^0.163.0 대신 실제로는 HEAD의 0.251.0이 로드되어 대량의
API 불일치 허위 에러가 발생. package.json은 관측 기간 동안 167회 변경됨 →
구조적 문제로 판단.

**해결**: lockfile 해시 기반 node_modules 캐시로 전환
(decisions.md 2026-09-03 "Phase 2 러너: node_modules 심볼릭 링크 → lockfile
해시 캐시로 변경" 참고). 결과:

| 항목 | 값 |
|---|---|
| 관측 기간 481개 커밋의 고유 lockfile 해시 수 | 113 (실제 설치 필요 횟수) |
| lockfile 읽기 실패 | 2건 (미조사) |
| install 소요(캐시 미스, warm store, --frozen-lockfile --ignore-scripts) | 평균 18.8초 (표본 5건: 22.56, 14.97, 15.78 및 20샘플 중 다수) |
| install 실패율 (관측 기간 전체 균등분포 20개 샘플, 2025-08-21~2026-07-28) | 0/20 (0%) |

lockfile 캐시 방식 적용 후 before 3개 커밋(5d1f2a6f, f7ca5834, 600a3d28) tsc
에러: 126 → 54개로 감소. 그러나 0은 아니었음 — 확인 결과 그 시점(lockfile 기준
tsc 5.9.2) 실제 코드에 진짜 타입 에러 54개가 존재했음 (TS2322 prop 타입 불일치,
TS2305 export 누락, TS2307 모듈 not found 등 실제 컴파일 에러). "HEAD 기준 tsc
baseline 0"이 과거 커밋에는 성립하지 않는다는 근거가 됨 → tsc도 biome처럼
"부모 대비 신규 에러 수"로 전환 (decisions.md 참고).

또한 tsc 5.9.2에는 --ignoreDeprecations의 값 "6.0"이 존재하지 않아
TS5103(Invalid value)으로 tsc 실행 자체가 실패함을 확인. lockfile 방식에서는
baseUrl 경고 자체가 애초에 발생하지 않으므로(그 시절 tsc에 해당 검사가 없음)
플래그를 제거하는 게 맞다고 판단, 철회함.

**BROKE 라벨 2개 커밋의 확정 tsc 에러 수** (lockfile 캐시 적용, 플래그 유무
무관하게 동일값 확인):

| sha | 이전 보고값(부정확) | 확정값 |
|---|---|---|
| 683b956b9faa | 92 → 72 (매핑 착오) | **90** |
| 21b56d29224f | 150 → 7 (매핑 착오) | **25** |

두 커밋 모두 lockfile이 tsc 6.0.3을 요구해 baseUrl 문제 자체가 없었음(그래서
플래그 유무가 결과에 영향을 주지 않음). 이전에 보고했던 72/7은 캐시 재사용
타이밍 문제로 부정확했던 값이며 90/25가 확정값.

**미측정**: 481개 lockfile 캐시 히트율 실측치(설계상 (481-113)/481≈76.5%가
히트 예상이나 전체를 돌려보지는 않음), 오래된 커밋(2025-08-21 이전)에서의
install 실패 여부(20개 샘플이 그 시점부터 시작해 아직 관측 못함), lockfile
읽기 실패 2건의 원인.

## 방향 전환: Phase 2/3 보류, MCP preflight 에이전트로 직행 (2026-09-03)

정확도-비용 곡선 측정(Phase 2/3 전수 실험)을 보류하고, 기존 evidence 3종 +
policy를 그대로 재사용해 실사용 가능한 preflight MCP 서버를 먼저 완성했다.
data/changes.jsonl, docs/ 기록은 유지 (실험은 나중에 재개 가능).

구현: mcp_server/server.py (FastMCP, python-mcp-sdk 1.29.1 -- mcp 2.x는
FastMCP가 MCPServer로 개명되며 API가 바뀌어 브리프 §10 "FastMCP" 지정에 맞춰
'mcp[cli]<2'로 고정 설치). preflight_check 툴 하나만 노출, config는
tsc+biome+import_graph_impact 고정.

tsc.py/biome.py에 절대 개수 모드(parent_repo_path=None, 기본)를 추가했다.
부모 비교 모드(parent_repo_path 지정)는 삭제하지 않고 그대로 남겨 Phase 2/3
재개 시 재사용 가능.

**실측 로그 (target/umami, HEAD=26e236c9)**:

1. 클린 상태 (changed_files 자동판단, git diff 결과 0개): outcome=READY,
   tsc 0 errors (26.2초), biome 0 errors, import_graph_impact 0 routes.
   total_duration_s=30.6
2. src/lib/auth.ts에 타입 에러 1개 인위 주입
   (`const _preflight_test_var: number = "...";`): outcome=**BLOCKED**,
   finding=TYPE_ERROR(file=src/lib/auth.ts, TS2322), actions=[DEPLOY
   executable=false approval_required=true]. total_duration_s=29.4
3. git checkout으로 원복: outcome=**READY** 복귀. total_duration_s=26.4
4. changed_files 명시 지정 + LookupField.tsx에 debugger문 주입:
   outcome=BLOCKED, finding=LINT_ERROR(1 error(s)),
   AFFECTED_ROUTES finding에 58개 route 정확히 나열. 원복 후 재확인 생략
   (biome.py 단위 검증에서 이미 확인된 패턴).
5. MCP stdio 프로토콜 실제 확인 (python -m mcp_server.server를 subprocess로
   띄우고 mcp.ClientSession으로 접속): list_tools() -> ['preflight_check']
   1개만 노출. call_tool("preflight_check", {"repo_path": "target/umami"})
   결과가 직접 함수 호출과 동일한 §6 스키마 JSON으로 반환됨을 확인.

**미측정**: repo_path 외부 레포(umami가 아닌 임의 프로젝트)에서의 동작,
changed_files가 매우 큰 경우의 성능, Claude Code/Cursor 실제 클라이언트 연결
(stdio 프로토콜 수준까지만 검증, 실제 IDE 통합은 미검증).
