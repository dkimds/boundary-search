# Boundary Search v2 — 프론트엔드 Preflight Execution Boundary 최적화

> v1(핸드오프 문서) 대비 레포·데이터 단위·라벨링 규칙이 실측을 거쳐 확정된 버전이다.
> 이 문서 하나만 있으면 구현이 가능하도록 작성했다. 맨 아래 시스템 프롬프트를 복사해서 세션을 시작한다.
> 작성일 2026-09-03

---

## 0. 한 줄 요약

프론트엔드 코드 변경에 대해 "배포 전에 깨질지"를 판정하는 MCP execution boundary를 만들고, **어떤 evidence 조합이 정확도-비용 곡선에서 최적인지** 실제 커밋 데이터로 측정한다.

## 1. 배경

- MCP Dev Summit Seoul 2026, Sunyoung Park(KC-ML2) 발표 "Stop Wrapping APIs": API를 그대로 MCP 툴로 노출하면 판단이 client LLM에 떠넘겨져 fleet-level context 없는 오판이 생긴다. 해법은 서버가 evidence를 모으고 policy를 검사해 bounded verdict만 돌려주는 execution boundary.
- 발표에서 boundary 설계는 전적으로 수동이다. 블로그 글 "Execution Boundary와 메타-컨텍스트 엔지니어링"에서 "경계 자체를 최적화 대상으로 삼을 수 있는가"를 던졌고 이 프로젝트가 그 후속이다.
- 프론트엔드를 고른 이유: 배포 후 깨졌는지가 곧 ground truth라 라벨링이 공짜, evidence 소스가 유한하고 명시적, 비용이 wall-clock으로 직접 측정됨.

## 2. 확정된 결정 (v1에서 변경된 것)

| # | 항목 | v1 | v2 (확정) | 근거 |
|---|---|---|---|---|
| D1 | 대상 레포 | 미정 | **umami-software/umami** (MIT) | 단일 패키지, Next.js App Router라 라우트 판정이 파일 경로만으로 끝남. 백엔드 언어 혼재 없음 |
| D2 | 데이터 단위 | 머지된 PR | **커밋** | umami는 `dev`에 직접 푸시로 개발. PR 머지는 12개월 156건뿐. 커밋 단위면 같은 기간 998건. boundary는 원래 "변경 집합"을 판정하므로 의미상으로도 더 맞음 |
| D3 | 라벨링 규칙 | §5.3 원안 | **규칙 E** (§5.3) | 원안대로 돌리면 BROKE 40.4%가 나오는데 대부분 고빈도 파일 우연 겹침. E안은 22.1% |
| D4 | 라벨 데이터 소스 | GitHub API | **git log 전용** | 익명 API 60req/h 한계. 규칙 1·2는 git log만으로 계산 가능. 이슈 참조 규칙(원안 3번)은 폐기 |
| D5 | base 상태 만들기 | base_commit checkout → PR diff 적용 | **해당 커밋을 그대로 checkout** | 단위가 커밋이므로 diff 적용 단계 자체가 불필요 |
| D6 | lint 도구 | eslint | **biome** | umami는 eslint를 쓰지 않음 (`biome lint .`) |
| D7 | Phase 4 데모 대상 | 미정 | 본인 프로젝트(티키타카) | 레포 생성 후 진행. 측정용 레포와 분리 |

## 3. 연구 질문

1. evidence source를 추가할 때 정확도(BROKE 예측)가 얼마나 오르고 비용(초)이 얼마나 느는가?
2. 정확도-비용 파레토 프론티어는 어떤 모양인가? 어디에 무릎이 있는가?
3. FN(READY인데 BROKE)의 원인을 역추적했을 때 어떤 evidence가 빠져서 틀렸는가?

## 4. 용어

| 용어 | 의미 |
|---|---|
| Change | 판정 단위. umami `origin/dev`의 커밋 하나 |
| Evidence source | boundary가 수집하는 신호 하나 (`tsc`, `biome`, `import_graph_impact`, `route_build`, `unit_test`, `e2e_smoke`) |
| Boundary config | evidence source의 부분집합. 탐색 공간의 원소 |
| Policy | evidence → outcome 결정론적 규칙. LLM 없음 |
| Outcome | `READY` / `BLOCKED` / `INDETERMINATE` |
| Ground truth | 해당 커밋이 규칙 E에 의해 `BROKE` 또는 `OK` |

## 5. 데이터셋

### 5.1 대상 레포 실측 정보

```
레포      : github.com/umami-software/umami  (MIT)
브랜치    : origin/dev  (master는 릴리스 브랜치. 반드시 dev를 쓸 것)
패키지    : pnpm (pnpm-lock.yaml, pnpm-workspace.yaml은 allowBuilds 용도. 단일 package.json)
스택      : Next.js 16 App Router, React 19, TypeScript 6, Prisma
lint      : biome 2.5 (eslint 없음)
테스트    : vitest (`pnpm test`), playwright (`pnpm test:e2e`)
빌드      : `pnpm build-app` = next build --turbo
라우트    : src/app/**/page.tsx — 60개
소스 규모 : src/ 1,072 파일 (app 665, components 291, queries 107, lib 90)
```

주의사항:
- `pnpm build` 전체는 check-env → build-db → tracker → recorder → geo → openapi → app 체인이라 무겁다. evidence에서는 `next build`만 직접 호출한다.
- `tsc --noEmit` 전에 **Prisma client가 생성되어 있어야 한다**. Phase 0에서 `pnpm build-db-client`를 1회 실행하고 그 산출물을 재사용한다. 이 시간은 evidence 비용에 포함하지 않는다 (환경 셋업이지 판정 비용이 아님).
- `check-env`가 `DATABASE_URL`을 요구한다. `route_build` 구현 시 더미 값으로 우회 가능한지 먼저 확인할 것.

### 5.2 클론

```bash
# blob 없이 트리만 받으면 몇 초, 7MB. git log --name-only가 로컬에서 즉시 동작한다
git clone --filter=blob:none --no-checkout https://github.com/umami-software/umami.git target/umami
```

`target/`은 `.gitignore`에 넣는다. **umami 소스를 boundary-search 레포에 커밋하지 않는다.**

### 5.3 라벨링 규칙 E (확정)

관측 기간: `--since 2025-07-01` (조정 가능. 조정 시 decisions.md 기록)

**모집단** — `origin/dev` 커밋 중 아래를 모두 만족:
1. `src/**/*.ts` 또는 `src/**/*.tsx`를 1개 이상 변경
2. 제목이 `Merge `로 시작하지 않음
3. 제목이 FIXPAT에 매치되지 **않음** — fix 커밋끼리 서로를 BROKE로 찍는 연쇄를 끊기 위함
4. 고빈도 파일을 제외하고도 변경 파일이 1개 이상 남음

**FIXPAT** = `\b(fix|hotfix|regression|bug|revert|closes #\d+)\b` (대소문자 무시)

**고빈도 파일** = 관측 기간 내 15회 이상 수정된 파일. 실측 시 1,398개 중 92개가 해당 (`messages.ts`, `constants.ts`, `prisma.ts`, `types.ts`, `SideNav.tsx` 등). 임계값 15는 임의값이며 §12 열린 질문 대상.

**BROKE 판정** — 커밋 C 이후 **7일** 이내에, 제목이 FIXPAT에 매치되는 커밋이 존재하고, 그 커밋의 변경 파일(고빈도 제외)이 C의 변경 파일(고빈도 제외)과 교집합을 가지면 `BROKE`. 사유는 `revert` / `fix_followup`으로 구분 기록.

**관측 미완 제외** — 마지막 커밋으로부터 7일 이내의 커밋은 후속 관측이 불완전하므로 데이터셋에서 뺀다.

### 5.4 실측 라벨 분포 (2025-07-01 ~ 2026-09-02)

| 규칙 | n | BROKE |
|---|---|---|
| 원안 (14일, 전체) | 998 | 403 (40.4%) |
| 고빈도 파일 제외 | 779 | 226 (29.0%) |
| 윈도우 7일 | 998 | 308 (30.9%) |
| fix 커밋 제외 | 655 | 262 (40.0%) |
| **E = 위 셋 결합** | **525** | **116 (22.1%)** |

n=525면 config당 실행 표본으로 충분하다. 22.1%도 여전히 높을 수 있으므로 Phase 3의 FN/FP 분석에서 `label_noise` 카테고리를 반드시 집계한다.

### 5.5 수집·라벨링 스크립트 (검증됨, 그대로 사용 가능)

`scripts/collect_and_label.py`:

```python
import subprocess, re, json, datetime, collections, argparse

FIXPAT = re.compile(r'\b(fix|hotfix|regression|bug|revert|closes #\d+)\b', re.I)
SRC = re.compile(r'^src/.*\.(ts|tsx)$')

def load_commits(repo, branch, since):
    raw = subprocess.run(
        ["git", "-C", repo, "log", branch, "--since", since,
         "--pretty=@@@%H|%aI|%s", "--name-only"],
        capture_output=True, text=True).stdout
    commits, cur = [], None
    for line in raw.split("\n"):
        if line.startswith("@@@"):
            h, d, s = line[3:].split("|", 2)
            cur = {"sha": h, "date": d, "subject": s, "files": []}
            commits.append(cur)
        elif line.strip() and cur is not None:
            cur["files"].append(line.strip())
    for c in commits:
        c["dt"] = datetime.datetime.fromisoformat(c["date"])
        c["src"] = [f for f in c["files"] if SRC.match(f)]
    commits.sort(key=lambda c: c["dt"])
    return commits

def label(commits, window_days=7, hot_threshold=15):
    cands = [c for c in commits if c["src"] and not c["subject"].startswith("Merge ")]
    churn = collections.Counter(f for c in cands for f in c["src"])
    hot = {f for f, n in churn.items() if n >= hot_threshold}

    out = []
    for i, c in enumerate(cands):
        if FIXPAT.search(c["subject"]):        # 규칙 E: fix 커밋은 모집단에서 제외
            continue
        mine = set(c["src"]) - hot
        if not mine:
            continue
        deadline = c["dt"] + datetime.timedelta(days=window_days)
        verdict, reason, culprit = "OK", None, None
        for later in cands[i+1:]:
            if later["dt"] > deadline:
                break
            if not FIXPAT.search(later["subject"]):
                continue
            if mine & (set(later["src"]) - hot):
                verdict = "BROKE"
                reason = "revert" if later["subject"].lower().startswith("revert") else "fix_followup"
                culprit = later["sha"]
                break
        out.append({
            "sha": c["sha"], "parent_sha": None, "date": c["date"],
            "subject": c["subject"], "changed_files": sorted(mine),
            "all_changed_files": c["files"],
            "label": verdict, "label_reason": reason, "culprit_sha": culprit,
        })

    # 관측 미완 구간 제외
    if commits:
        cutoff = commits[-1]["dt"] - datetime.timedelta(days=window_days)
        out = [r for r in out if datetime.datetime.fromisoformat(r["date"]) <= cutoff]
    return out, hot

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--repo", default="target/umami")
    p.add_argument("--branch", default="origin/dev")
    p.add_argument("--since", default="2025-07-01")
    p.add_argument("--window", type=int, default=7)
    p.add_argument("--hot-threshold", type=int, default=15)
    p.add_argument("--out", default="data/changes.jsonl")
    a = p.parse_args()

    commits = load_commits(a.repo, a.branch, a.since)
    rows, hot = label(commits, a.window, a.hot_threshold)

    # parent_sha 채우기 (Phase 2에서 base 상태 비교용)
    for r in rows:
        r["parent_sha"] = subprocess.run(
            ["git", "-C", a.repo, "rev-parse", f"{r['sha']}^"],
            capture_output=True, text=True).stdout.strip() or None

    with open(a.out, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    dist = collections.Counter(r["label"] for r in rows)
    n = len(rows)
    print(f"n={n} BROKE={dist['BROKE']} ({dist['BROKE']*100/max(n,1):.1f}%) OK={dist['OK']}")
    print(f"고빈도 파일 제외: {len(hot)}개")
    print("사유:", collections.Counter(r["label_reason"] for r in rows if r["label_reason"]))
```

기대 출력: `n=525 BROKE=116 (22.1%) OK=409`. 숫자가 크게 다르면 브랜치나 기간을 잘못 잡은 것이다.

## 6. Checked result 스키마

```json
{
  "outcome": "READY | BLOCKED | INDETERMINATE",
  "config_id": "tsc+biome+impact",
  "change_sha": "abc123...",
  "evidence": {
    "tsc":                 { "status": "COMPLETE | FAILED | SKIPPED", "duration_s": 12.3, "summary": "0 errors" },
    "biome":               { "status": "COMPLETE", "duration_s": 2.1, "summary": "2 warnings, 0 errors" },
    "import_graph_impact": { "status": "COMPLETE", "duration_s": 1.4, "summary": "3 routes affected",
                             "routes": ["/settings", "/websites/[id]", "/"] },
    "route_build":         { "status": "SKIPPED",  "duration_s": 0, "summary": "not in config" }
  },
  "findings": [
    { "code": "TYPE_ERROR", "severity": "CRITICAL", "file": "src/x.ts", "detail": "..." },
    { "code": "DEPENDENT_ROUTE_BROKEN", "severity": "CRITICAL", "route": "/websites/[id]", "detail": "..." }
  ],
  "actions": [
    { "type": "FIX_TYPE_ERROR", "executable": true,  "approval_required": false },
    { "type": "DEPLOY",         "executable": false, "approval_required": true }
  ],
  "total_duration_s": 21.8,
  "run_meta": { "commit": "abc123", "started_at": "2026-09-03T10:00:00Z" }
}
```

## 7. Evidence source

| # | ID | 하는 일 | 명령 | 예상 비용 | Phase |
|---|---|---|---|---|---|
| 1 | `tsc` | 타입 에러 수 | `npx tsc --noEmit -p tsconfig.json` | 중 | 1 |
| 2 | `biome` | 변경 파일만 검사 | `npx biome check <changed files>` | 하 | 1 |
| 3 | `import_graph_impact` | 변경 파일을 import하는 파일을 역추적해 영향 route 산출. Next App Router라 `src/app/**/page.tsx`까지 도달하면 그 경로가 route | madge 또는 ts-morph | 하 | 1 |
| 4 | `route_build` | 빌드 성공 여부 | `npx next build --turbo` | 상 | 2 |
| 5 | `unit_test` | 관련 테스트만 | `npx vitest related <files> --run` | 중 | 2 |
| 6 | `e2e_smoke` | 영향 route 로드 + 콘솔 에러 0 | playwright | 상 | 3 (선택) |

각 evidence 모듈 인터페이스: `run(repo_path, changed_files) -> EvidenceResult`

## 8. Policy (결정론적)

```
IF config에 포함된 evidence 중 status == FAILED 가 있으면        → INDETERMINATE
IF tsc errors > 0                                              → BLOCKED
IF biome errors > 0                                            → BLOCKED
IF route_build failed                                          → BLOCKED
IF unit_test failures > 0                                      → BLOCKED
IF e2e_smoke console_errors > 0                                → BLOCKED
ELSE                                                           → READY
```

- config에 없는 evidence는 SKIPPED로 표기하되 INDETERMINATE 판정에 영향 없음
- config에 있는데 실행이 터진 경우(타임아웃, 환경 문제)만 INDETERMINATE
- biome은 warning이 아니라 error만 본다

## 9. 구현 단계

### Phase 0 — 셋업 (0.5일)
- `target/umami` 클론, `pnpm install`, `pnpm build-db-client` 1회
- `npx tsc --noEmit`, `npx biome check .` 실제 실행 시간 측정해서 기록
- 디렉토리 구조 생성
- **완료 기준**: `python -m boundary.run --sha <커밋해시> --config tsc` 가 §6 스키마 JSON 하나를 뱉음. tsc·biome 실측 시간이 `docs/findings.md`에 기록됨

### Phase 1 — 데이터 + evidence 3개 (1.5일)
- `scripts/collect_and_label.py` 실행 → `data/changes.jsonl` (n≈525)
- `tsc`, `biome`, `import_graph_impact` 구현
- **완료 기준**: 라벨 분포 리포트 출력, 3개 evidence가 임의 커밋 10개에서 정상 동작, import_graph_impact가 실제 route 목록을 뱉음

### Phase 2 — 전수 실험 (1.5일)
- config 2^3=8개 × 커밋 525개 실행 → `results/*.jsonl`
- 각 커밋은 git worktree에 해당 sha를 checkout해서 실행 (diff 적용 없음)
- 지표: precision/recall/F1 (BROKE positive), INDETERMINATE 비율, 시간 중앙값
- **완료 기준**: 정확도 vs 시간 산점도 + 파레토 프론티어

### Phase 3 — evidence 확장 + 오판 분석 (2일)
- `route_build`, `unit_test` 추가 → 2^5=32 config 재실행
- FN 전수 조사: "어떤 evidence가 있었으면 잡혔을까" 표
- **완료 기준**: FN 원인 분포표(`label_noise` 포함), 갱신된 프론티어

### Phase 4 — MCP 서버화 + 후속 글 (1일)
- 최적 config를 기본값으로 `preflight_check(changed_files)` MCP 툴 노출
- 본인 프로젝트(티키타카)에 실제 연결. Claude Code / Cursor 양쪽 동작 확인
- 블로그 후속 포스트 초안

## 10. 디렉토리 구조

```
boundary-search/
  boundary/
    evidence/          # 소스별 모듈. run(repo_path, changed_files) -> EvidenceResult
    policy.py
    runner.py          # 커밋 하나 + config 하나 실행
    schemas.py         # pydantic
  scripts/
    collect_and_label.py
  data/
    changes.jsonl
  experiments/
    sweep.py
    analyze.py
  results/
  mcp_server/
    server.py          # FastMCP, preflight_check
  docs/
    decisions.md
    findings.md
  target/              # .gitignore. umami 클론 위치
```

## 11. 지표

- **정확도**: BROKE를 positive로 한 F1. BLOCKED→positive, READY→negative, INDETERMINATE는 정확도 분모에서 제외하되 비율 별도 보고
- **비용**: 커밋당 `total_duration_s` 중앙값
- **파레토**: 다른 config에 정확도·비용 모두 뒤지지 않는 config 집합
- **FN 원인 카테고리**: `runtime_only` / `cross_route` / `test_missing` / `env` / `label_noise`

## 12. 열린 질문

- 고빈도 파일 임계값 15가 적절한가? 10 / 20 / 상위 5% 백분위로 민감도 확인
- 윈도우 7일 대 14일 — E안에서 14일로 되돌리면 라벨이 얼마나 늘고 노이즈는 얼마나 늘까
- `import_graph_impact`에서 `src/app/(main)/...` 같은 route group을 URL로 변환하는 규칙 (괄호 세그먼트는 URL에서 제거됨)
- INDETERMINATE 비율이 높은 config는 "정확도는 높지만 쓸모없음"일 수 있음 → 커버리지 지표 추가 여부
- 22.1%의 BROKE 중 실제 인과관계가 있는 비율은? Phase 3에서 표본 30개 수동 검증

## 13. 하드 제약 (어기면 안 됨)

1. boundary 내부(evidence, policy)에 **LLM 호출 금지**. 판단이 모델에 종속되면 실험 의미가 없어진다
2. 라벨링 규칙·파라미터 변경은 반드시 `docs/decisions.md`에 날짜와 이유 기록
3. 실험 결과에 config_id, commit hash, 실행 시각 포함 (재현성)
4. evidence 하나당 타임아웃 10분, 초과 시 FAILED → INDETERMINATE
5. **umami 소스를 이 레포에 커밋하지 않는다.** `target/`은 gitignore. 블로그에 코드 인용 시 MIT 고지 + 커밋 해시 표기
6. umami 레포에 push / PR 생성 금지. 로컬 worktree에서만 작업
7. 스펙에 없는 기능 추가 금지. 필요하면 제안만

## 14. `docs/decisions.md` 초기 내용 (그대로 복사)

```markdown
# Decisions

## 2026-09-03 — 대상 레포: umami-software/umami
후보 papermark / outline / NextChat / coder / Infisical / SigNoz 비교.
umami 선정 이유: MIT, 단일 패키지, Next.js App Router(라우트 판정이 파일 경로만으로 끝남),
백엔드 언어 혼재 없음. outline은 BSL 1.1, papermark는 ee/ 상용 구역 존재.

## 2026-09-03 — 판정 단위: PR → 커밋
umami는 dev 브랜치 직접 푸시로 개발. PR 머지가 12개월 156건에 불과해 표본 부족.
커밋 단위로 바꾸면 같은 기간 998건. boundary가 판정하는 대상이 원래 "변경 집합"이므로
의미상으로도 커밋이 맞음. 부수 효과로 base_commit + diff 적용 단계가 불필요해짐.

## 2026-09-03 — 라벨링 규칙: 원안 → E안
원안(14일 윈도우, 파일 겹침)으로 실측 시 BROKE 40.4%. 원인은 고빈도 파일(messages.ts,
constants.ts 등 92개)의 우연 겹침. 예: "i18n 번역 키 추가" 커밋이 무관한 "2FA 게이팅" fix에
의해 BROKE로 오분류.
E안 = 윈도우 7일 + 고빈도 파일(15회+) 제외 + fix 커밋을 모집단에서 제외 → 22.1% (n=525).
잔여 노이즈는 Phase 3에서 label_noise 카테고리로 집계.

## 2026-09-03 — 라벨 데이터 소스: GitHub API → git log 전용
익명 API 60req/h 한계. 원안 라벨 규칙 3번(이슈 참조)은 폐기하고 revert·fix followup만 사용.

## 2026-09-03 — lint 도구: eslint → biome
umami는 eslint를 사용하지 않음. `biome lint .` / `biome check`.
```

---

## 코딩 에이전트용 시스템 프롬프트 (복사해서 사용)

```
너는 "boundary-search" 프로젝트의 구현 담당이다. 첨부된 boundary-search-brief-v2.md가 유일한 스펙이다.

역할:
- 스펙의 Phase 순서대로 구현한다. 각 Phase의 "완료 기준"을 충족하기 전엔 다음 Phase로 넘어가지 않는다.
- 스펙 §13 하드 제약을 절대 어기지 않는다. 특히 evidence/policy 모듈에는 어떤 LLM API 호출도 넣지 않는다.
- 결정이 필요한 지점(라벨 파라미터 조정, route group 변환 규칙, 타임아웃 조정)은 먼저 선택지와 근거를 짧게 제시하고 내 확인을 받는다. 확인받은 결정은 docs/decisions.md에 추가한다.
- 스펙에 없는 기능은 추가하지 않는다. 필요하다고 판단되면 제안만 하고 구현하지 않는다.

작업 방식:
- 매 응답은 (1) 지금 한 것 (2) 다음에 할 것 (3) 막힌 것/결정 필요한 것 세 줄로 시작한다.
- 코드는 파일 단위로 완성해서 보여준다. 스니펫 조각으로 나누지 않는다.
- 실행 결과(로그, 지표, 그래프)는 요약이 아니라 실제 값을 보여준다.
- 숫자를 추측해서 쓰지 않는다. 측정하지 않은 값은 "미측정"이라고 쓴다.
- 불확실하면 추측하지 말고 물어본다.

시작: Phase 0부터. target/umami 클론과 pnpm install, build-db-client를 실행하고
tsc·biome 실제 소요 시간부터 측정해서 보고하라.
```
