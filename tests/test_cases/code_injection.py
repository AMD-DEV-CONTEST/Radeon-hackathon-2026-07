# Test Case 3: Python Code Injection and Deserialization
# Expected: 3 critical risks (eval, exec, pickle)

import os
import pickle
import subprocess

# VULN: CWE-95 - eval() executes arbitrary code
def calculate(expr):
    return eval(expr)  # CRITICAL: code injection

# VULN: CWE-95 - exec() executes arbitrary code
def run_code(code_str):
    exec(code_str)  # CRITICAL: code injection

# VULN: CWE-502 - pickle.loads() on untrusted data
def load_object(data_bytes):
    return pickle.loads(data_bytes)  # CRITICAL: deserialization

# VULN: CWE-78 - os.system() command injection
def run_cmd(cmd):
    os.system(cmd)  # HIGH: command injection

# SAFE: uses subprocess with list (no shell)
def safe_cmd(args):
    return subprocess.run(args, shell=False)
