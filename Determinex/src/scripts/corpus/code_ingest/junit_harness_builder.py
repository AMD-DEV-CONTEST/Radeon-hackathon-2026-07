"""
JUnit harness builder — constructs minimal JUnit test harnesses for Java repair tasks.

Given a JavaRepairTask (from java_task_extractor), builds a self-contained
test project that:
  1. Contains the mutated (broken) source
  2. Has the JUnit test that exposes the failure
  3. Can be built with `mvn test` or `gradle test`
  4. Records the trace in corpus format

Output structure:
  work_dir/
    task_id/
      src/main/java/...  ← mutated source
      src/test/java/...  ← failing test
      pom.xml            ← minimal Maven wrapper
      trace.json         ← corpus-ready trace
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_MINIMAL_POM = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
                             http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.determinex.corpus</groupId>
  <artifactId>{artifact_id}</artifactId>
  <version>1.0.0</version>
  <packaging>jar</packaging>
  <properties>
    <maven.compiler.source>11</maven.compiler.source>
    <maven.compiler.target>11</maven.compiler.target>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.junit.jupiter</groupId>
      <artifactId>junit-jupiter</artifactId>
      <version>5.10.0</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-surefire-plugin</artifactId>
        <version>3.1.2</version>
      </plugin>
    </plugins>
  </build>
</project>
"""


@dataclass
class HarnessResult:
    task_id: str
    harness_path: Path
    build_success: bool
    test_failed_as_expected: bool
    repair_verified: bool
    trace: dict[str, Any]
    error: str | None = None


class JUnitHarnessBuilder:
    """Builds and validates JUnit test harnesses for Java repair tasks."""

    def __init__(self, work_dir: Path, timeout: int = 180):
        self._work_dir = work_dir
        self._timeout = timeout

    def build_harness(
        self,
        task_id: str,
        broken_source: str,
        test_source: str,
        repaired_source: str,
        class_name: str = "Subject",
        test_class_name: str = "SubjectTest",
    ) -> HarnessResult:
        """
        Build a minimal Maven project, verify it fails with broken source,
        then verify it passes with repaired source.
        """
        harness_dir = self._work_dir / task_id
        harness_dir.mkdir(parents=True, exist_ok=True)

        main_dir = harness_dir / "src" / "main" / "java" / "com" / "determinex" / "corpus"
        test_dir = harness_dir / "src" / "test" / "java" / "com" / "determinex" / "corpus"
        main_dir.mkdir(parents=True, exist_ok=True)
        test_dir.mkdir(parents=True, exist_ok=True)

        # Write POM
        pom = harness_dir / "pom.xml"
        pom.write_text(_MINIMAL_POM.format(artifact_id=task_id.replace("_", "-")), encoding="utf-8")

        # Write broken source
        (main_dir / f"{class_name}.java").write_text(broken_source, encoding="utf-8")
        (test_dir / f"{test_class_name}.java").write_text(test_source, encoding="utf-8")

        # Verify broken source fails
        rc_broken, out_broken, err_broken = self._mvn(harness_dir, ["test"])
        test_failed = rc_broken != 0

        # Write repaired source and verify it passes
        (main_dir / f"{class_name}.java").write_text(repaired_source, encoding="utf-8")
        rc_fixed, out_fixed, err_fixed = self._mvn(harness_dir, ["test"])
        repair_verified = rc_fixed == 0

        trace = {
            "task_id": task_id,
            "language": "java",
            "build_system": "maven",
            "broken_compiles": rc_broken != -2,  # -2 = mvn not found
            "test_failed_as_expected": test_failed,
            "repair_verified": repair_verified,
            "broken_error": (err_broken + out_broken)[:500],
            "repair_output": out_fixed[:200],
            "broken_source_hash": hashlib.blake2b(
                broken_source.encode(), digest_size=16
            ).hexdigest(),
            "repaired_source_hash": hashlib.blake2b(
                repaired_source.encode(), digest_size=16
            ).hexdigest(),
        }

        # Write trace
        trace_path = harness_dir / "trace.json"
        trace_path.write_text(json.dumps(trace, indent=2), encoding="utf-8")

        return HarnessResult(
            task_id=task_id,
            harness_path=harness_dir,
            build_success=True,
            test_failed_as_expected=test_failed,
            repair_verified=repair_verified,
            trace=trace,
        )

    def _mvn(self, cwd: Path, args: list[str]) -> tuple[int, str, str]:
        try:
            result = subprocess.run(
                ["mvn", "--no-transfer-progress", "-q"] + args,
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=self._timeout,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "TIMEOUT"
        except FileNotFoundError:
            return -2, "", "mvn not found"
