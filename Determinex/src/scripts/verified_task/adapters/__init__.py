"""Benchmark adapters that emit TaskSpec."""

from .aider_polyglot_adapter import aider_polyglot_task_spec
from .bigcodebench_adapter import bigcodebench_task_spec
from .debugbench_adapter import debugbench_task_spec
from .ide_repair_adapter import ide_repair_task_spec
from .programbench_adapter import programbench_task_spec
from .security_adapter import security_task_spec
from .sql_bench_adapter import sql_task_spec
from .swebench_pro_adapter import swebench_pro_task_spec
from .swelancer_adapter import swelancer_task_spec
from .terminalbench_adapter import terminal_task_spec

__all__ = [
    "aider_polyglot_task_spec",
    "bigcodebench_task_spec",
    "debugbench_task_spec",
    "ide_repair_task_spec",
    "programbench_task_spec",
    "security_task_spec",
    "sql_task_spec",
    "swebench_pro_task_spec",
    "swelancer_task_spec",
    "terminal_task_spec",
]
