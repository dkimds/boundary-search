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
