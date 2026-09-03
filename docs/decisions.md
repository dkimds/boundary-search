# Decisions

## 2026-09-03 — 대상 레포: umami-software/umami
MIT, 단일 패키지, Next.js App Router라 라우트 판정이 파일 경로만으로 끝남.
outline은 BSL 1.1, papermark는 ee/ 상용 구역이 있어 제외.

## 2026-09-03 — 판정 단위: PR → 커밋
umami는 dev 브랜치 직접 푸시로 개발. PR 머지가 12개월 156건뿐이라 표본 부족.
커밋 단위면 같은 기간 998건. base_commit + diff 적용 단계도 불필요해짐.

## 2026-09-03 — 라벨링 규칙: 원안 → E안
원안(14일 윈도우)으로는 BROKE 40.4%. 고빈도 파일의 우연 겹침이 원인.
E안 = 윈도우 7일 + 고빈도 파일(15회+) 제외 + fix 커밋을 모집단에서 제외.

## 2026-09-03 — 라벨 데이터 소스: GitHub API → git log 전용
익명 API 60req/h 한계. 이슈 참조 규칙은 폐기하고 revert·fix followup만 사용.

## 2026-09-03 — lint 도구: eslint → biome
umami는 eslint를 사용하지 않음.

## 2026-09-03 — 관측 기간 및 고빈도 임계값
--since 2025-09-01 기준 n=481, BROKE 119 (24.7%), 고빈도 파일 56개 제외.
기간을 2025-07-01로 늘리면 518 / 22.4% / 92개로 변동. 임계값 15회가 기간 길이에 종속됨.
→ Phase 1에서 백분위 또는 월당 빈도로 정규화할 것. 그 전까지 기간 고정.

## 2026-09-03 — Prisma 환경변수
prisma generate가 DATABASE_URL을 요구. 실제 접속은 하지 않으므로 더미 postgres URL을
.env에 넣어 해결. route_build에서 실 DB 필요 여부는 별도 확인.

## 2026-09-03 — biome evidence 정의
umami HEAD에 lint 에러 6개 존재. 절대 개수로 판정하면 전 커밋이 오판됨.
→ "변경 파일 한정 + 부모 커밋 대비 신규 에러 수"로 정의. biome check는 미사용.
구체 계산: 변경 파일(수정/추가, src/**/*.ts|tsx)마다 현재(child) biome lint 에러 개수와
부모 커밋 시점 동일 파일의 biome lint 에러 개수를 각각 세어 파일별 (child − parent)를
구하고, 음수는 0으로 클램프한 뒤 합산. 신규 추가 파일은 parent 에러 0으로 취급.
진단 항목의 line/column 매칭이 아닌 개수 차이 기반 — 스펙 문구("부모 커밋 대비 신규
에러 수")를 그대로 카운트로 구현한 것.

## 2026-09-03 — import_graph_impact: route group 변환 규칙
madge로 얻은 src 기준 상대 경로에서 route 경로로 변환하는 규칙을 확정:
1. 파일명이 page.tsx/route.ts면 제거, 앞의 "app" 세그먼트 제거
2. 괄호로 감싼 세그먼트( (main), (collect) 등)는 제거 — Next.js route group은 URL에
   나타나지 않음 (스펙 §12 명시)
3. [websiteId] 같은 동적 세그먼트는 그대로 유지
4. 남은 세그먼트를 "/"로 join, 앞에 "/" 부착. 비어있으면 루트 "/"
예: app/(main)/websites/[websiteId]/settings/page.tsx → /websites/[websiteId]/settings
영향 route 판정은 변경 파일을 madge 역방향 그래프에서 BFS해 도달 가능한 모든
src/app/**/page.tsx를 route로 변환. 변경 파일 자체가 page.tsx면 그 route도 포함.

## 2026-09-03 — findings/actions 생성 규칙
§6 findings/actions 생성 알고리즘은 스펙에 명시 없음. 최소 해석으로 확정:
- findings: tsc 에러 1개당 code=TYPE_ERROR/severity=CRITICAL/file 기록.
  biome 신규 에러 1개당 code=LINT_ERROR/severity=CRITICAL/file 기록.
  import_graph_impact 실행 시 code=AFFECTED_ROUTES/severity=INFO/routes=[...] 1건 기록
  (route가 0개여도 기록). policy는 severity=="CRITICAL" finding만 BLOCKED 판정에
  사용하고 INFO는 무시. AFFECTED_ROUTES를 남기는 이유는 §3-3 FN 원인 역추적
  (cross_route 분류)에 route 정보가 필요하기 때문 — 안 남기면 Phase 3에서 재현 불가.
- actions: outcome==READY면 DEPLOY(executable=true, approval_required=false) 1건.
  BLOCKED/INDETERMINATE면 DEPLOY(executable=false, approval_required=true) 1건.
  finding별 FIX_* 액션은 생성하지 않음. 자동 수정 제안은 Phase 4에서 재검토.

## 2026-09-03 — evidence 인터페이스 확장 및 parent 비교 처리
§7 원 시그니처 run(repo_path, changed_files)를 run(repo_path, changed_files,
parent_repo_path=None)로 확장. Phase 2 러너가 커밋마다 worktree를 파므로 parent
커밋용 worktree 경로를 evidence에 전달하기 위함.
- biome: parent_repo_path가 None이면 status=FAILED, summary="parent worktree
  unavailable" 반환 (절대 에러 수로 조용히 대체하지 않음 — §8 "실행이 터진 경우만
  INDETERMINATE"를 그대로 활용, 새 규칙 불필요). parent에 없는 신규 파일은 parent
  에러 0으로 취급.
- tsc: baseline 에러 0(Phase 0 실측)이므로 parent 비교 불필요. parent_repo_path를
  받되 사용하지 않고 절대 에러 수로 판정. 비대칭을 tsc.py 상단 주석에 명시.

## 2026-09-03 — Phase 2 러너: node_modules 심볼릭 링크 → lockfile 해시 캐시로 변경
worktree마다 node_modules를 단일 심볼릭 링크(HEAD 기준)로 공유하는 방식은
과거 커밋에서 대량 허위 tsc 에러를 유발함을 실측으로 확인. 원인: 2025-08-21
커밋의 package.json은 @umami/react-zen@^0.163.0을 요구하는데 실제 링크된
node_modules는 HEAD 기준 0.251.0이 설치돼 있어 API 불일치로 126개 허위 에러
발생. package.json이 관측 기간(2025-07-01~) 동안 167회 변경돼 구조적 문제로 판단.
→ 각 커밋의 pnpm-lock.yaml 내용 해시(sha256 앞 16자)를 키로
  .cache/node_modules/<lockfile-hash>/ 에 설치하고, worktree에서는 그 디렉토리를
  심볼릭 링크한다. 같은 lockfile을 가진 연속 커밋은 설치를 재사용.
- 캐시 미스일 때만 pnpm install --frozen-lockfile --ignore-scripts 실행.
  --ignore-scripts를 붙이는 이유: pnpm-workspace.yaml의 allowBuilds 설정이
  과거 커밋마다 달라 postinstall(husky 등)이 pnpm 11의 ERR_PNPM_IGNORED_BUILDS로
  exit 1을 내는 사례를 실측 확인(2025-08-21 커밋). postinstall 스크립트는
  evidence 판정(tsc/biome)에 필요하지 않고, prisma client는 별도로 명시 실행하므로
  스킵해도 무방.
- pnpm store(전역, ~/Library/pnpm/store)는 공유해 재다운로드 비용을 줄인다.
- 설치 후 prisma generate를 커밋 시점 스키마로 실행. .env 심볼릭 링크는 기존대로.
- install/generate 소요 시간은 evidence duration_s에 포함하지 않고 러너가 별도
  필드(setup_duration_s 등, runner.py 구현 시 확정)로 기록한다 (§9 Phase0 "환경
  셋업이지 판정 비용이 아니다" 원칙을 러너 단위로 확장 적용).

실측 (2026-09-03):
- 관측 기간 481개 커밋의 pnpm-lock.yaml 고유 해시: 113개 (실제 설치 필요 횟수).
  lockfile 읽기 실패 2건(파일 없음 등, 원인 미조사).
- warm pnpm store 상태 install 소요(캐시 미스, --frozen-lockfile --ignore-scripts):
  약 15~23초 (표본 5건 평균 18.8초).
- install 실패율: 관측 기간 전체(2025-08-21~2026-07-28)에 균등 분포시킨 20개
  샘플에서 0/20 (0%) 실패. worktree add, install, prisma generate 전부 성공.

## 2026-09-03 — tsc evidence: 절대 개수 → 부모 대비 신규 개수로 통일 (biome과 동일)
"HEAD 기준 tsc baseline 0"은 HEAD만의 관측이었음이 확인됨. lockfile 해시 캐시
방식으로 과거 커밋을 정확한 시점 node_modules로 재검사한 결과, 2025-08-21
커밋 3건에서 이미 54개의 실제(진짜) 타입 에러가 존재했음 (RealtimeData export
누락, FormFieldProps 불일치 등 실제 코드 문제). 절대 개수로 판정하면 이런 커밋들이
전부 허위 BLOCKED가 됨.
→ tsc도 biome과 동일하게 "변경 파일 없이 레포 전체 대비 부모 커밋 대비 신규 에러
  수"로 통일. tsc.py 상단의 "tsc는 비대칭적으로 절대 개수를 쓴다"는 이전 결정과
  주석은 철회. parent_repo_path가 None이면 biome과 동일하게 status=FAILED.
비용 변화: 커밋당 tsc 실행이 1회 → 2회(child+parent)로 늘어 약 46초로 증가
(findings.md 기록).

## 2026-09-03 — tsc evidence: --ignoreDeprecations "6.0" 플래그 철회
이전 결정("tsconfig baseUrl deprecated 경고를 --ignoreDeprecations "6.0"으로
억제")은 node_modules 심볼릭 링크 방식(고정 tsc 6.0.3) 전제 하의 것이었음.
lockfile 해시 캐시로 전환해 각 커밋 시점의 tsc 버전(예: 5.9.2)을 그대로 쓰게
되면서 baseUrl deprecated 경고 자체가 발생하지 않음이 되므로(그 시절 tsc에는
해당 경고가 아직 없었음) 플래그가 불필요해짐. 오히려 구버전 tsc는
"--ignoreDeprecations 6.0"이라는 값 자체를 모르는 경우가 있어(TS5103: Invalid
value) 플래그를 계속 붙이면 tsc 실행 자체가 실패하는 새 문제가 생김.
→ 플래그 제거. 버전 감지/조건부 분기 로직도 추가하지 않음(스펙에 없는 기능).
명령은 다시 "npx tsc --noEmit -p tsconfig.json" (§7 원 정의와 동일).

## 2026-09-03 — Phase 2/3 보류, MCP preflight 서버로 방향 전환
정확도-비용 곡선 실험(전수 실행)을 보류하고 §9 Phase 4(MCP 서버화)를 먼저
진행한다. 기존 evidence 3종(tsc/biome/import_graph_impact) + policy.py를 그대로
재사용. data/changes.jsonl, docs/decisions.md, docs/findings.md는 유지해
실험을 나중에 재개할 수 있게 한다.
- mcp_server/server.py: FastMCP로 preflight_check 툴 하나만 노출.
  config는 tsc+biome+import_graph_impact로 고정 (config 선택 기능은 스펙에
  없으므로 추가하지 않음).
- python mcp SDK를 'mcp[cli]<2'로 고정 설치. mcp 2.x는 FastMCP를 MCPServer로
  개명하며 API를 변경했는데, 브리프 §10이 명시적으로 "FastMCP"를 지정하므로
  1.x 계열(FastMCP 존재)을 사용.
- tsc.py/biome.py에 "절대 개수 모드"(parent_repo_path=None)를 추가. 기존
  "부모 대비 신규 개수 모드"(parent_repo_path 지정)는 삭제하지 않고 그대로
  유지 -- Phase 2/3 재개 시 재사용. preflight_check는 절대 개수 모드만 쓴다
  (worktree, lockfile 캐시, 부모 커밋 비교 없이 현재 작업 트리를 현재
  node_modules로 그대로 검사).
- changed_files 미지정 시 git diff --name-only HEAD + git ls-files --others
  (untracked)를 합쳐 src/**/*.ts|tsx만 필터링해 자동 판단.
