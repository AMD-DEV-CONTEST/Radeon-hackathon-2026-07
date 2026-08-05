from swe_experiments.verifier import CodeVerifier, CheckResult, VerifierReport, rank_verifier_reports


class FakeRunner:
    def __init__(self, files=None, failures=None):
        self.files = set(files or [])
        self.failures = set(failures or [])
        self.commands = []

    def __call__(self, command, timeout):
        self.commands.append((command, timeout))
        if command.startswith("test -f"):
            path = command.split(" ", 2)[-1].strip("'\"")
            return {"output": "", "exit_code": 0 if path in self.files else 1}
        if command == "git diff --name-only":
            return {"output": "src/foo.py\n", "exit_code": 0}
        for marker in self.failures:
            if marker in command:
                return {"output": f"failed: {command}", "exit_code": 1}
        return {"output": "ok", "exit_code": 0}


def test_v1_runs_diff_and_compile_gates():
    runner = FakeRunner()
    report = CodeVerifier(runner, mode="V1").verify()
    names = [check.name for check in report.checks]
    assert report.passed
    assert names == ["diff_check", "python_compile"]


def test_v2_selects_existing_targeted_tests():
    runner = FakeRunner(files={"tests/test_foo.py"})
    report = CodeVerifier(runner, mode="V2").verify()
    assert report.passed
    assert report.targeted_tests == ["tests/test_foo.py"]
    assert any(check.name == "targeted_tests" for check in report.checks)


def test_verifier_rejects_failed_gate_and_reports_evidence():
    runner = FakeRunner(failures={"git diff --check"})
    report = CodeVerifier(runner, mode="V1").verify()
    assert not report.passed
    assert report.verdict == "reject"
    assert "diff_check" in report.failure_summary


def test_verifier_rejects_empty_workspace():
    class EmptyRunner(FakeRunner):
        def __call__(self, command, timeout):
            if command == "git diff --name-only":
                return {"output": "", "exit_code": 0}
            return super().__call__(command, timeout)

    report = CodeVerifier(EmptyRunner(), mode="V1").verify()
    assert not report.passed
    assert "changes_present" in report.failure_summary


def test_v3_requires_discriminative_reproduction():
    runner = FakeRunner(failures={"before"})
    report = CodeVerifier(runner, mode="V3").verify(
        reproduction_before="echo before",
        reproduction_after="echo after",
    )
    assert report.passed
    assert report.reproduction == {"before": "fail", "after": "pass", "discriminative": True}


def test_candidate_reports_rank_accepting_evidence_first():
    reject = VerifierReport("reject", "V4")
    accept = VerifierReport("accept", "V4", [CheckResult("tests", True, 0)])
    assert rank_verifier_reports([reject, accept])[0] is accept


def test_llm_review_is_recorded_without_changing_deterministic_verdict():
    report = VerifierReport("reject", "V5", llm_review={"verdict": "accept"})
    payload = report.to_dict()
    assert payload["passed"] is False
    assert payload["llm_review"]["verdict"] == "accept"
