"""Language-to-validator profiles for benchmark adapters.

These profiles are deliberately command-shaped. Benchmarks with known setup can
override them, but adapters should start here so ProgramBench, Terminal-Bench,
Aider Polyglot, DebugBench, SWE-style repo repair, SQL, and security loops use
one language map.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class LanguageProfile:
    language: str
    file_globs: tuple[str, ...]
    setup_commands: tuple[str, ...] = field(default_factory=tuple)
    validation_commands: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""


LANGUAGE_PROFILES: dict[str, LanguageProfile] = {
    "bash": LanguageProfile(
        language="bash",
        file_globs=("*.sh", "run.sh", "Makefile"),
        validation_commands=("bash -n *.sh",),
        notes="Prefer explicit task commands over broad shell globs when available.",
    ),
    "python": LanguageProfile(
        language="python",
        file_globs=("*.py", "pyproject.toml", "pytest.ini"),
        validation_commands=("python -m pytest -q",),
    ),
    "go": LanguageProfile(
        language="go",
        file_globs=("*.go", "go.mod", "go.sum"),
        validation_commands=("go test ./...",),
    ),
    "rust": LanguageProfile(
        language="rust",
        file_globs=("*.rs", "Cargo.toml", "Cargo.lock"),
        validation_commands=("cargo test --locked",),
        notes="Fallback to cargo test if the benchmark source has no lockfile.",
    ),
    "typescript": LanguageProfile(
        language="typescript",
        file_globs=("*.ts", "*.tsx", "package.json", "tsconfig.json"),
        validation_commands=("npm test -- --runInBand", "npx tsc --noEmit"),
        notes="Adapters may drop npm test when benchmark only requires typecheck.",
    ),
    "javascript": LanguageProfile(
        language="javascript",
        file_globs=("*.js", "*.jsx", "package.json"),
        validation_commands=("npm test -- --runInBand",),
    ),
    "java": LanguageProfile(
        language="java",
        file_globs=("*.java", "pom.xml", "build.gradle", "gradlew"),
        validation_commands=(
            "if exist mvnw.cmd (mvnw.cmd test) else if exist pom.xml (mvn test) else if exist gradlew.bat (gradlew.bat test) else (javac *.java)",
        ),
    ),
    "c": LanguageProfile(
        language="c",
        file_globs=("*.c", "*.h", "Makefile", "CMakeLists.txt"),
        validation_commands=("if exist Makefile (make test) else (gcc -Wall -Wextra -Werror *.c)",),
    ),
    "cpp": LanguageProfile(
        language="cpp",
        file_globs=("*.cc", "*.cpp", "*.hpp", "*.h", "Makefile", "CMakeLists.txt"),
        validation_commands=(
            "if exist Makefile (make test) else (g++ -std=c++20 -Wall -Wextra -Werror *.cpp)",
        ),
    ),
    "ruby": LanguageProfile(
        language="ruby",
        file_globs=("*.rb", "Gemfile", "Rakefile"),
        validation_commands=("if exist Rakefile (bundle exec rake test) else (ruby -c *.rb)",),
    ),
    "php": LanguageProfile(
        language="php",
        file_globs=("*.php", "composer.json"),
        validation_commands=("php -l *.php",),
    ),
    "sql": LanguageProfile(
        language="sql",
        file_globs=("*.sql",),
        validation_commands=("python -m scripts.verified_task.sql_smoke",),
        notes="Benchmark adapters should replace this with sqlite/postgres execution comparators.",
    ),
}


ALIASES = {
    "sh": "bash",
    "shell": "bash",
    "py": "python",
    "golang": "go",
    "rs": "rust",
    "ts": "typescript",
    "js": "javascript",
    "c++": "cpp",
}


def get_language_profile(language: str) -> LanguageProfile:
    key = language.strip().lower()
    key = ALIASES.get(key, key)
    try:
        return LANGUAGE_PROFILES[key]
    except KeyError as exc:
        known = ", ".join(sorted(LANGUAGE_PROFILES))
        raise KeyError(f"unknown language profile {language!r}; known: {known}") from exc


def default_validation_commands(language: str) -> list[str]:
    return list(get_language_profile(language).validation_commands)
