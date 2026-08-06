"""Tests for CodeRisk Agent - Static Analyzer"""

import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.static_analyzer import StaticAnalyzer
from core.models import CodeFile, Language, Severity


@pytest.fixture
def analyzer():
    return StaticAnalyzer()


# ─── CWE-120: Buffer Overflow ────────────────────────────────────

class TestBufferOverflow:
    def test_detects_gets(self, analyzer):
        """gets() should be flagged as CRITICAL (CWE-120)"""
        code = '#include <stdio.h>\nint main() { char buf[10]; gets(buf); }'
        f = CodeFile(path="test.c", content=code, language=Language.C)
        risks = analyzer.analyze(f)
        assert any(r.cwe_id == "CWE-120" and r.severity == Severity.CRITICAL for r in risks)

    def test_detects_strcpy(self, analyzer):
        """strcpy() should be flagged as HIGH (CWE-120)"""
        code = '#include <string.h>\nvoid f(char *s) { char b[10]; strcpy(b, s); }'
        f = CodeFile(path="test.c", content=code, language=Language.C)
        risks = analyzer.analyze(f)
        assert any("strcpy" in r.title and r.severity == Severity.HIGH for r in risks)


# ─── CWE-78: Command Injection ──────────────────────────────────

class TestCommandInjection:
    def test_detects_system_c(self, analyzer):
        """system() in C should be flagged as HIGH (CWE-78)"""
        code = '#include <stdlib.h>\nvoid f() { system("ls"); }'
        f = CodeFile(path="test.c", content=code, language=Language.C)
        risks = analyzer.analyze(f)
        assert any(r.cwe_id == "CWE-78" and r.severity == Severity.HIGH for r in risks)

    def test_detects_os_system_python(self, analyzer):
        """os.system() in Python should be flagged as HIGH (CWE-78)"""
        code = 'import os\nos.system("ls")'
        f = CodeFile(path="test.py", content=code, language=Language.PYTHON)
        risks = analyzer.analyze(f)
        assert any(r.cwe_id == "CWE-78" and r.severity == Severity.HIGH for r in risks)


# ─── CWE-95: Code Injection ─────────────────────────────────────

class TestCodeInjection:
    def test_detects_eval(self, analyzer):
        """eval() should be flagged as CRITICAL (CWE-95)"""
        code = 'x = eval(input())'
        f = CodeFile(path="test.py", content=code, language=Language.PYTHON)
        risks = analyzer.analyze(f)
        assert any(r.cwe_id == "CWE-95" and r.severity == Severity.CRITICAL for r in risks)

    def test_detects_exec(self, analyzer):
        """exec() should be flagged as CRITICAL (CWE-95)"""
        code = 'exec("print(1)")'
        f = CodeFile(path="test.py", content=code, language=Language.PYTHON)
        risks = analyzer.analyze(f)
        assert any(r.cwe_id == "CWE-95" and r.severity == Severity.CRITICAL for r in risks)


# ─── CWE-502: Deserialization ───────────────────────────────────

class TestDeserialization:
    def test_detects_pickle(self, analyzer):
        """pickle.loads() should be flagged as CRITICAL (CWE-502)"""
        code = 'import pickle\ndata = pickle.loads(b"abc")'
        f = CodeFile(path="test.py", content=code, language=Language.PYTHON)
        risks = analyzer.analyze(f)
        assert any(r.cwe_id == "CWE-502" and r.severity == Severity.CRITICAL for r in risks)


# ─── Safe Code ──────────────────────────────────────────────────

class TestSafeCode:
    def test_safe_c_code(self, analyzer):
        """Safe C code should produce no critical/high risks"""
        code = '''
#include <stdio.h>
int main() {
    int x = 42;
    printf("%d\\n", x);
    return 0;
}
'''
        f = CodeFile(path="safe.c", content=code, language=Language.C)
        risks = analyzer.analyze(f)
        critical = [r for r in risks if r.severity in (Severity.CRITICAL, Severity.HIGH)]
        assert len(critical) == 0

    def test_safe_python_code(self, analyzer):
        """Safe Python code should produce no critical/high risks"""
        code = '''
def add(a, b):
    return a + b

result = add(1, 2)
print(result)
'''
        f = CodeFile(path="safe.py", content=code, language=Language.PYTHON)
        risks = analyzer.analyze(f)
        critical = [r for r in risks if r.severity in (Severity.CRITICAL, Severity.HIGH)]
        assert len(critical) == 0


# ─── Test Case Files ────────────────────────────────────────────

class TestTestCaseFiles:
    def test_buffer_overflow_file(self, analyzer):
        """buffer_overflow.c should have 2+ critical/high risks"""
        path = Path(__file__).parent / "test_cases" / "buffer_overflow.c"
        f = CodeFile.from_path(path)
        risks = analyzer.analyze(f)
        high_risks = [r for r in risks if r.severity in (Severity.CRITICAL, Severity.HIGH)]
        assert len(high_risks) >= 2

    def test_command_injection_file(self, analyzer):
        """command_injection.c should have 2+ high risks"""
        path = Path(__file__).parent / "test_cases" / "command_injection.c"
        f = CodeFile.from_path(path)
        risks = analyzer.analyze(f)
        high_risks = [r for r in risks if r.severity in (Severity.CRITICAL, Severity.HIGH)]
        assert len(high_risks) >= 2

    def test_code_injection_file(self, analyzer):
        """code_injection.py should have 3+ critical risks"""
        path = Path(__file__).parent / "test_cases" / "code_injection.py"
        f = CodeFile.from_path(path)
        risks = analyzer.analyze(f)
        critical = [r for r in risks if r.severity == Severity.CRITICAL]
        assert len(critical) >= 3

    def test_memory_issues_file(self, analyzer):
        """memory_issues.c should detect malloc and double free"""
        path = Path(__file__).parent / "test_cases" / "memory_issues.c"
        f = CodeFile.from_path(path)
        risks = analyzer.analyze(f)
        assert len(risks) >= 1
