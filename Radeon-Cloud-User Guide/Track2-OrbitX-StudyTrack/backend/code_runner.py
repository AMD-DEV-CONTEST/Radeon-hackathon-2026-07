import subprocess
import sys
import os
import tempfile
import re

MAX_EXECUTION_TIME = 10
MAX_OUTPUT_LENGTH = 2000
MAX_CODE_LENGTH = 20000
MAX_STDIN_LENGTH = 4096

BLOCKED_PATTERNS = [
    r'(?i)\b(import|from)\s+(os|subprocess|socket|requests|urllib|http\.client|pty|shutil)\b',
    r'(?i)\bos\.(system|popen|spawn|exec|remove|rename|mkdir|chmod|chdir)\b',
    r'(?i)\bsubprocess\.',
    r'(?i)\bsocket\.',
    r'(?i)\b(open|eval|exec|compile|__import__)\s*\(',
]


def _blocked_reason(code: str) -> str | None:
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, code):
            return 'Code execution rejected unsafe operation.'
    return None


def run_python_code(code: str, stdin_input: str = '') -> dict:
    code = code or ''
    stdin_input = stdin_input or ''

    if len(code) > MAX_CODE_LENGTH:
        return {
            'success': False,
            'stdout': '',
            'stderr': f'Code exceeds the maximum length of {MAX_CODE_LENGTH} characters.',
            'return_code': -1,
            'timed_out': False,
        }

    blocked_reason = _blocked_reason(code)
    if blocked_reason:
        return {
            'success': False,
            'stdout': '',
            'stderr': blocked_reason,
            'return_code': -1,
            'timed_out': False,
        }

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = os.path.join(tmp_dir, 'solution.py')
        with open(tmp_path, 'w', encoding='utf-8') as tmp:
            tmp.write(code)

        env = os.environ.copy()
        for key in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP'):
            env.pop(key, None)
        env.update({
            'PYTHONDONTWRITEBYTECODE': '1',
            'PYTHONIOENCODING': 'utf-8',
        })

        process = subprocess.Popen(
            [sys.executable, '-I', tmp_path],
            cwd=tmp_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        try:
            stdout, stderr = process.communicate(
                input=stdin_input[:MAX_STDIN_LENGTH],
                timeout=MAX_EXECUTION_TIME,
            )
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()

            return {
                'success': False,
                'stdout': '',
                'stderr': f'Execution timed out after {MAX_EXECUTION_TIME} seconds.',
                'return_code': -1,
                'timed_out': True,
            }
        except Exception as e:
            return {
                'success': False,
                'stdout': '',
                'stderr': 'Code execution failed.',
                'return_code': -1,
                'timed_out': False,
            }

        return {
            'success': process.returncode == 0,
            'stdout': stdout[:MAX_OUTPUT_LENGTH],
            'stderr': stderr[:MAX_OUTPUT_LENGTH],
            'return_code': process.returncode,
            'timed_out': False,
        }
