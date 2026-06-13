"""Run the behavioral eval suite against the live agent.

    python -m evals.run

Exits non-zero if any scenario fails, so it can gate a demo or CI step.
Requires the Ollama model to be available (it drives the real agent).
"""
from __future__ import annotations

import sys
import uuid

from app.agent.service import chat
from app.data.seed import seed
from evals.grounding import check_grounding, _tool_evidence
from evals.judge import judge_violation
from evals.scenarios import SCENARIOS, Scenario


def _run_scenario(s: Scenario) -> list[str]:
    """Execute a scenario, return a list of failure messages (empty == pass)."""
    # Reseed before EACH scenario so rows created by an earlier one don't leak in.
    seed()
    session = f"eval-{uuid.uuid4().hex[:8]}"
    failures: list[str] = []
    tools_seen: set[str] = set()
    tools_succeeded: set[str] = set()
    escalated = False
    last_response = ""
    prior_evidence = ""  # tool evidence accumulated across earlier turns (session-wide)

    for turn in s.turns:
        result = chat(session, turn)
        tools_seen.update(result.trace.tool_names)
        tools_succeeded.update(c.name for c in result.trace.tools_called if c.success)
        escalated = escalated or result.trace.requires_human
        last_response = result.response
        if s.check_grounding and result.trace.used_tools:
            grounded, violations = check_grounding(result.trace, prior_evidence)
            if not grounded:
                failures.extend(violations)
        prior_evidence += " " + _tool_evidence(result.trace)

    missing = s.expect_tools - tools_seen
    if missing:
        failures.append(f"faltó invocar: {sorted(missing)}")

    forbidden = s.forbid_tools & tools_seen
    if forbidden:
        failures.append(f"no debió invocar: {sorted(forbidden)}")

    forbidden_ok = s.forbid_successful & tools_succeeded
    if forbidden_ok:
        failures.append(f"no debió tener éxito: {sorted(forbidden_ok)}")

    if s.expect_requires_human is not None and escalated != s.expect_requires_human:
        failures.append(
            f"requires_human esperado={s.expect_requires_human}, obtenido={escalated}"
        )

    for needle in s.response_contains:
        if needle.lower() not in last_response.lower():
            failures.append(f"respuesta no contiene esperado: '{needle}'")
    if s.response_contains_any and not any(
        n.lower() in last_response.lower() for n in s.response_contains_any
    ):
        failures.append(f"respuesta no contiene ninguno de: {s.response_contains_any}")
    for needle in s.response_not_contains:
        if needle.lower() in last_response.lower():
            failures.append(f"respuesta contiene prohibido: '{needle}'")

    if s.judge_violation_question and judge_violation(
        s.judge_violation_question, s.turns[-1], last_response
    ):
        failures.append("LLM-judge detectó incumplimiento de la regla de negocio")

    return failures


def main() -> int:
    seed()  # baseline; _run_scenario reseeds before each scenario for isolation
    print("=" * 70)
    print("EVAL SUITE — Retail AI Agent")
    print("=" * 70)
    total_fail = 0
    for s in SCENARIOS:
        failures = _run_scenario(s)
        status = "PASS ✅" if not failures else "FAIL ❌"
        print(f"\n[{status}] {s.name}")
        for f in failures:
            print(f"    - {f}")
        total_fail += bool(failures)

    print("\n" + "=" * 70)
    print(f"{len(SCENARIOS) - total_fail}/{len(SCENARIOS)} scenarios passed")
    print("=" * 70)
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
