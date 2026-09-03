"""결정론적 policy. §8 규칙을 그대로 구현한다.

이 모듈에는 LLM 호출이 없다 (스펙 §13-1).
evidence 결과만 입력으로 받아 outcome/findings/actions를 산출한다.
"""

from __future__ import annotations

from boundary.schemas import Action, EvidenceResult, EvidenceStatus, Finding, Outcome, Severity


def _tsc_findings(result: EvidenceResult) -> list[Finding]:
    errors = result.extra.get("errors", [])
    return [
        Finding(
            code="TYPE_ERROR",
            severity=Severity.CRITICAL,
            file=e.get("file"),
            detail=e.get("detail", ""),
        )
        for e in errors
    ]


def _biome_findings(result: EvidenceResult) -> list[Finding]:
    errors = result.extra.get("errors", [])
    return [
        Finding(
            code="LINT_ERROR",
            severity=Severity.CRITICAL,
            file=e.get("file"),
            detail=e.get("detail", ""),
        )
        for e in errors
    ]


def _import_graph_impact_findings(result: EvidenceResult) -> list[Finding]:
    # route 0개여도 기록 (decisions.md 2026-09-03 findings/actions 생성 규칙).
    # severity=INFO이므로 policy의 BLOCKED 판정에는 관여하지 않고, §3-3의
    # cross_route 원인 역추적을 위해 route 목록을 결과 JSON에 남기기만 한다.
    routes = result.extra.get("routes", [])
    return [
        Finding(
            code="AFFECTED_ROUTES",
            severity=Severity.INFO,
            detail=f"{len(routes)} routes affected",
            routes=list(routes),
        )
    ]


def _route_build_findings(result: EvidenceResult) -> list[Finding]:
    if result.extra.get("success", True):
        return []
    return [
        Finding(
            code="ROUTE_BUILD_FAILED",
            severity=Severity.CRITICAL,
            detail=result.summary,
        )
    ]


def _unit_test_findings(result: EvidenceResult) -> list[Finding]:
    failures = result.extra.get("failures", [])
    return [
        Finding(
            code="UNIT_TEST_FAILURE",
            severity=Severity.CRITICAL,
            file=f.get("file"),
            detail=f.get("detail", ""),
        )
        for f in failures
    ]


def _e2e_smoke_findings(result: EvidenceResult) -> list[Finding]:
    errors = result.extra.get("console_errors", [])
    return [
        Finding(
            code="E2E_CONSOLE_ERROR",
            severity=Severity.CRITICAL,
            route=e.get("route"),
            detail=e.get("detail", ""),
        )
        for e in errors
    ]


_FINDING_BUILDERS = {
    "tsc": _tsc_findings,
    "biome": _biome_findings,
    "import_graph_impact": _import_graph_impact_findings,
    "route_build": _route_build_findings,
    "unit_test": _unit_test_findings,
    "e2e_smoke": _e2e_smoke_findings,
}


def evaluate(evidence: dict[str, EvidenceResult]) -> tuple[Outcome, list[Finding], list[Action]]:
    """§8 policy 그대로.

    evidence: config에 포함된 evidence만 실제로 실행된 EvidenceResult를 갖고,
    config에 없는 evidence는 status=SKIPPED로 채워져 들어온다 (runner 책임).
    """
    findings: list[Finding] = []
    for evidence_id, result in evidence.items():
        builder = _FINDING_BUILDERS.get(evidence_id)
        if builder is None:
            continue
        if result.status != EvidenceStatus.COMPLETE:
            continue
        findings.extend(builder(result))

    # config에 포함됐는데 실행이 실패한 경우만 INDETERMINATE (§8, §9 완료기준 아님)
    if any(r.status == EvidenceStatus.FAILED for r in evidence.values()):
        outcome = Outcome.INDETERMINATE
    elif any(f.severity == Severity.CRITICAL for f in findings):
        outcome = Outcome.BLOCKED
    else:
        outcome = Outcome.READY

    if outcome == Outcome.READY:
        actions = [Action(type="DEPLOY", executable=True, approval_required=False)]
    else:
        actions = [Action(type="DEPLOY", executable=False, approval_required=True)]

    return outcome, findings, actions
