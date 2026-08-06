#!/usr/bin/env python3
"""Deterministic scaffold, validation, and release builder for servo action packages."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


ACTION_ID = re.compile(r"^[a-z][a-z0-9-]*$")
RESERVED_ACTION_IDS = {
    "init", "lift-left", "lift-right", "lower-left", "lower-right",
    "stand", "relax", "shake-ears", "flash", "servo", "remove",
}
BRIDGE_METHODS = {
    "init_position", "lift_left", "lift_right", "hold_visible_position",
    "lower_left", "lower_right", "wave_hands", "stand", "relax",
    "shake_ears", "flash",
}
ROOT = Path(__file__).resolve().parents[1]
ACTIONS_ROOT = ROOT / "examples" / "plugins" / "servo" / "servo_actions"
RELEASE_ROOT = ROOT / ".rdk-agent" / "releases" / "current"
ACTION_HISTORY_ROOT = ROOT / ".rdk-agent" / "action-history"
BASE_SKILL = ROOT / "skills" / "servo-control" / "SKILL.md"
SCHEMA = "rdk-servo-action/v1"


class ContractError(RuntimeError):
    def __init__(self, code: str, message: str, path: Path | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


def emit(payload: dict[str, Any], status: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(status)


def action_directory(action_id: str) -> Path:
    if not ACTION_ID.fullmatch(action_id):
        raise ContractError("ACTION-ID-001", "动作 ID 必须以小写字母开头，且只含小写字母、数字和连字符")
    if action_id in RESERVED_ACTION_IDS:
        raise ContractError("ACTION-ID-003", "动作 ID 与内置命令冲突：%s" % action_id)
    return ACTIONS_ROOT / action_id


def read_manifest(directory: Path) -> dict[str, Any]:
    path = directory / "registry.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ContractError("ACTION-REGISTRY-001", "缺少 registry.json", path) from error
    except json.JSONDecodeError as error:
        raise ContractError("ACTION-REGISTRY-002", "registry.json 不是有效 JSON", path) from error
    if not isinstance(value, dict):
        raise ContractError("ACTION-REGISTRY-003", "registry.json 必须是对象", path)
    return value


def require_string(manifest: dict[str, Any], key: str, path: Path) -> str:
    value = manifest.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractError("ACTION-REGISTRY-004", "registry.json.%s 必须是非空字符串" % key, path)
    return value


def require_metadata_text(value: Any, label: str, path: Path | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("ACTION-METADATA-001", "%s 必须是非空字符串" % label, path)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ContractError("ACTION-METADATA-002", "%s 必须是无控制字符的单行文本" % label, path)
    return value.strip()


def markdown_text(value: str) -> str:
    return value.replace("`", "\\`")


def validate_action(directory: Path, allow_placeholder: bool = False) -> dict[str, Any]:
    manifest_path = directory / "registry.json"
    manifest = read_manifest(directory)
    if manifest.get("schema") != SCHEMA:
        raise ContractError("ACTION-REGISTRY-005", "registry.json.schema 必须为 %s" % SCHEMA, manifest_path)
    action_id = require_string(manifest, "id", manifest_path)
    if directory.name != action_id or not ACTION_ID.fullmatch(action_id):
        raise ContractError("ACTION-ID-002", "动作目录名必须与合法的 registry.json.id 完全一致", manifest_path)
    if action_id in RESERVED_ACTION_IDS:
        raise ContractError("ACTION-ID-003", "动作 ID 与内置命令冲突：%s" % action_id, manifest_path)
    require_metadata_text(manifest.get("description"), "registry.json.description", manifest_path)
    entrypoint = require_string(manifest, "entrypoint", manifest_path)
    if entrypoint != "action.py:run":
        raise ContractError("ACTION-ENTRYPOINT-001", "entrypoint 当前必须精确为 action.py:run", manifest_path)
    start = manifest.get("start")
    if start not in {"left", "right", "both", "none"}:
        raise ContractError("ACTION-START-001", "start 必须是 left、right、both 或 none", manifest_path)
    if manifest.get("arguments") != []:
        raise ContractError("ACTION-ARGS-002", "rdk-servo-action/v1 只支持无参数动作，arguments 必须为 []", manifest_path)
    skill = manifest.get("skill")
    if not isinstance(skill, dict) or not isinstance(skill.get("intentExamples"), list) or not skill["intentExamples"]:
        raise ContractError("ACTION-SKILL-001", "skill.intentExamples 必须包含至少一个自然语言示例", manifest_path)
    for item in skill["intentExamples"]:
        require_metadata_text(item, "skill.intentExamples[]", manifest_path)

    source_path = directory / "action.py"
    try:
        source = source_path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ContractError("ACTION-ENTRYPOINT-002", "缺少 action.py", source_path) from error
    try:
        tree = ast.parse(source, filename=str(source_path))
    except SyntaxError as error:
        raise ContractError("ACTION-PYTHON-001", "action.py 语法错误：%s" % error.msg, source_path) from error
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "context" and node.attr in {"calls", "mock_calls"}:
            raise ContractError("ACTION-BRIDGE-001", "action.py 不得访问测试桩字段 context.%s；必须调用硬件桥接方法" % node.attr, source_path)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ContractError("ACTION-SAFETY-001", "动作模块不得导入任何模块；只能调用硬件桥接白名单", source_path)

    named_run = next((node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run"), None)
    if not isinstance(named_run, ast.FunctionDef):
        raise ContractError("ACTION-ENTRYPOINT-003", "action.py 必须定义同步 run(context, params)", source_path)
    run = named_run
    valid_arguments = (
        not run.args.posonlyargs
        and [argument.arg for argument in run.args.args] == ["context", "params"]
        and not run.args.vararg
        and not run.args.kwonlyargs
        and not run.args.kwarg
        and not run.args.defaults
        and not run.args.kw_defaults
        and all(argument.annotation is None for argument in run.args.args)
        and run.returns is None
        and not run.decorator_list
    )
    if not valid_arguments:
        raise ContractError("ACTION-ENTRYPOINT-003", "action.py 必须定义无装饰器的同步 run(context, params)", source_path)
    for statement in tree.body:
        is_docstring = (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
        if statement is not run and not is_docstring:
            raise ContractError("ACTION-SAFETY-002", "action.py 顶层只能包含文档字符串和 run(context, params)", source_path)
    body = list(run.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    if not body:
        raise ContractError("ACTION-BRIDGE-002", "run(context, params) 必须至少调用一个硬件桥接方法", source_path)
    is_placeholder = (
        len(body) == 1
        and isinstance(body[0], ast.Raise)
        and isinstance(body[0].exc, ast.Call)
        and isinstance(body[0].exc.func, ast.Name)
        and body[0].exc.func.id == "NotImplementedError"
        and not body[0].exc.keywords
        and len(body[0].exc.args) <= 1
        and all(isinstance(argument, ast.Constant) and isinstance(argument.value, str) for argument in body[0].exc.args)
    )
    if allow_placeholder and is_placeholder:
        return manifest
    for statement in body:
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            raise ContractError("ACTION-SAFETY-002", "run 只能按顺序调用无参数硬件桥接方法", source_path)
        call = statement.value
        if not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name) or call.func.value.id != "context":
            raise ContractError("ACTION-SAFETY-002", "run 只能直接调用 context 的硬件桥接方法", source_path)
        if call.func.attr not in BRIDGE_METHODS:
            raise ContractError("ACTION-BRIDGE-002", "不允许的硬件桥接方法：context.%s" % call.func.attr, source_path)
        if call.args or call.keywords:
            raise ContractError("ACTION-BRIDGE-003", "rdk-servo-action/v1 的硬件桥接调用不能携带参数", source_path)
    return manifest


def archive_action(action_id: str, directory: Path) -> Path:
    history = ACTION_HISTORY_ROOT / action_id
    history.mkdir(parents=True, exist_ok=True)
    version = 1
    while (history / ("v%d" % version)).exists():
        version += 1
    destination = history / ("v%d" % version)
    os.replace(directory, destination)
    return destination


def scaffold(
    action_id: str,
    description: str | None = None,
    start: str = "both",
    intents: list[str] | None = None,
    fresh: bool = False,
) -> None:
    directory = action_directory(action_id)
    archived: Path | None = None
    if directory.exists():
        if not fresh:
            manifest = read_manifest(directory)
            if manifest.get("schema") != SCHEMA or manifest.get("id") != action_id or manifest.get("entrypoint") != "action.py:run":
                raise ContractError("ACTION-SCAFFOLD-002", "既有动作包不符合可复用契约：%s" % directory, directory / "registry.json")
            emit({"status": "existing", "actionId": action_id, "directory": str(directory.relative_to(ROOT))})
        archived = archive_action(action_id, directory)
    try:
        if start not in {"left", "right", "both", "none"}:
            raise ContractError("ACTION-START-001", "start 必须是 left、right、both 或 none")
        resolved_description = require_metadata_text(description or "待补充：%s 动作说明" % action_id, "description")
        resolved_intents = intents or ["待补充：%s 的自然语言触发语句" % action_id]
        if not resolved_intents:
            raise ContractError("ACTION-SKILL-001", "intentExamples 必须至少包含一项")
        resolved_intents = [require_metadata_text(item, "intentExamples[]") for item in resolved_intents]
        directory.mkdir(parents=True)
        (directory / "tests").mkdir()
        manifest = {
            "schema": SCHEMA,
            "id": action_id,
            "description": resolved_description,
            "entrypoint": "action.py:run",
            "start": start,
            "arguments": [],
            "skill": {"intentExamples": resolved_intents, "risk": "motion"},
        }
        (directory / "registry.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (directory / "action.py").write_text(
            '"""%s action package."""\n\n\ndef run(context, params):\n    """Implement the action using the supplied hardware bridge only."""\n    raise NotImplementedError("implement %s")\n' % (action_id, action_id),
            encoding="utf-8",
        )
        (directory / "tests" / "test_action.py").write_text(
            "import importlib.util\nimport unittest\nfrom pathlib import Path\n\n\nACTION_PATH = Path(__file__).resolve().parents[1] / 'action.py'\n\n\ndef load_run():\n    spec = importlib.util.spec_from_file_location('action_under_test', ACTION_PATH)\n    module = importlib.util.module_from_spec(spec)\n    assert spec and spec.loader\n    spec.loader.exec_module(module)\n    return module.run\n\n\nclass FakeContext:\n    def __init__(self):\n        self.calls = []\n\n    def __getattr__(self, name):\n        def record(*args, **kwargs):\n            self.calls.append(name)\n        return record\n\n\nclass ActionBehaviorTest(unittest.TestCase):\n    def test_action_behavior(self):\n        # Replace this one method with the requested behavior. Keep this file, loader and FakeContext.\n        self.fail('define the expected context calls for %s')\n\n\nif __name__ == '__main__':\n    unittest.main()\n" % action_id,
            encoding="utf-8",
        )
        (directory / "tests" / "test_contract.py").write_text(
            "import subprocess\nimport sys\nimport unittest\nfrom pathlib import Path\n\n\nclass ActionContractTest(unittest.TestCase):\n    def test_package_contract(self):\n        root = Path(__file__).resolve().parents[6]\n        result = subprocess.run([sys.executable, 'tools/servo_action.py', 'validate-scaffold', '%s'], cwd=root, capture_output=True, text=True)\n        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)\n\n\nif __name__ == '__main__':\n    unittest.main()\n" % action_id,
            encoding="utf-8",
        )
    except Exception:
        if archived is not None:
            shutil.rmtree(directory, ignore_errors=True)
            os.replace(archived, directory)
        raise
    payload = {"status": "scaffolded", "actionId": action_id, "directory": str(directory.relative_to(ROOT))}
    if archived is not None:
        payload["archived"] = str(archived.relative_to(ROOT))
    emit(payload)


def validate(action_id: str, allow_placeholder: bool = False) -> None:
    directory = action_directory(action_id)
    manifest = validate_action(directory, allow_placeholder=allow_placeholder)
    emit({"status": "passed", "actionId": action_id, "directory": str(directory.relative_to(ROOT)), "manifest": manifest})


def package_directories() -> list[Path]:
    if not ACTIONS_ROOT.exists():
        return []
    return sorted(directory for directory in ACTIONS_ROOT.iterdir() if directory.is_dir() and not directory.name.startswith("."))


def build() -> None:
    packages: list[tuple[Path, dict[str, Any]]] = []
    seen: set[str] = set()
    for directory in package_directories():
        manifest = validate_action(directory)
        action_id = manifest["id"]
        if action_id in seen:
            raise ContractError("ACTION-DISCOVERY-001", "发现重复动作 ID：%s" % action_id, directory / "registry.json")
        seen.add(action_id)
        packages.append((directory, manifest))
    if not packages:
        raise ContractError("ACTION-BUILD-001", "没有可构建的动作包", ACTIONS_ROOT)

    RELEASE_ROOT.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".servo-release-", dir=RELEASE_ROOT.parent))
    try:
        actions_destination = staging / "servo_actions"
        actions_destination.mkdir()
        catalog: list[dict[str, Any]] = []
        for directory, manifest in packages:
            shutil.copytree(directory, actions_destination / directory.name, ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"))
            catalog.append({"id": manifest["id"], "description": manifest["description"], "arguments": manifest["arguments"], "skill": manifest["skill"]})
        catalog_path = staging / "skill-catalog.json"
        catalog_path.write_text(json.dumps({"version": 1, "actions": catalog}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            base_skill = BASE_SKILL.read_text(encoding="utf-8").rstrip()
        except FileNotFoundError as error:
            raise ContractError("ACTION-SKILL-003", "缺少 servo-control 基础 Skill", BASE_SKILL) from error
        if not base_skill.startswith("---\nname: servo-control\n"):
            raise ContractError("ACTION-SKILL-004", "servo-control 基础 Skill frontmatter 无效", BASE_SKILL)

        skill_directory = staging / "skill"
        skill_directory.mkdir()
        skill_lines = [
            base_skill,
            "",
            "## 已发布动作包",
            "",
            "以下内容由 `tools/servo_action.py build` 从已验证动作包生成。动作式请求已授权执行一次，查询请求保持只读。",
            "",
        ]
        for entry in catalog:
            examples = "；".join(markdown_text(item) for item in entry["skill"]["intentExamples"])
            skill_lines.append("- `%s`：%s。触发示例：%s。命令：`sophonctl --board x5 servo %s`" % (
                entry["id"], markdown_text(entry["description"]), examples, entry["id"],
            ))
        skill_lines.extend([
            "",
            "执行前运行 `sophonctl --board x5 plugins list`。命令失败时报告真实输出，不得自动重复真实动作；无法从输出确认物理位移时请人类目视确认。",
            "",
        ])
        (skill_directory / "SKILL.md").write_text("\n".join(skill_lines), encoding="utf-8")
        shutil.copy2(catalog_path, skill_directory / "skill-catalog.json")
        digest = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
        (staging / "release.json").write_text(json.dumps({"schema": "rdk-servo-release/v1", "catalogSha256": digest}, indent=2) + "\n", encoding="utf-8")
        previous = RELEASE_ROOT.with_name("previous")
        if previous.exists():
            shutil.rmtree(previous)
        moved_previous = False
        if RELEASE_ROOT.exists():
            os.replace(RELEASE_ROOT, previous)
            moved_previous = True
        try:
            os.replace(staging, RELEASE_ROOT)
        except Exception:
            if moved_previous and previous.exists() and not RELEASE_ROOT.exists():
                os.replace(previous, RELEASE_ROOT)
            raise
        emit({"status": "built", "release": str(RELEASE_ROOT.relative_to(ROOT)), "actions": [manifest["id"] for _, manifest in packages], "catalogSha256": digest})
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("new", "validate", "validate-scaffold"):
        child = subparsers.add_parser(command)
        child.add_argument("action_id")
        if command == "new":
            child.add_argument("--description")
            child.add_argument("--start", default="both")
            child.add_argument("--intent", action="append")
            child.add_argument("--fresh", action="store_true")
    subparsers.add_parser("build")
    args = parser.parse_args()
    try:
        if args.command == "new":
            scaffold(args.action_id, args.description, args.start, args.intent, args.fresh)
        elif args.command == "validate":
            validate(args.action_id)
        elif args.command == "validate-scaffold":
            validate(args.action_id, allow_placeholder=True)
        else:
            build()
    except ContractError as error:
        payload: dict[str, Any] = {"status": "failed", "code": error.code, "message": str(error)}
        if error.path:
            payload["path"] = str(error.path.relative_to(ROOT) if error.path.is_relative_to(ROOT) else error.path)
        emit(payload, 1)


if __name__ == "__main__":
    main()
