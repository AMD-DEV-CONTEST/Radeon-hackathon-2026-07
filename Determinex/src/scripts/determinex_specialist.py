"""
determinex_specialist.py — Domain-specialist slot routing
=======================================================
Extends determinex_benchmark.py with domain-specific scoring beyond the four base
roles (ORACLE, ARCHITECT, BUILDER, MONITOR).

Specialist slots are benchmark-driven, architecture-agnostic:
  - Any model can fill any specialist slot
  - Assignment is always the highest composite specialist score
  - The same composite formula as determinex_benchmark.py (local vs API paths)

Domains:
  sql        — SQL query generation, schema design, stored procedures
  iac        — Terraform / Kubernetes / Dockerfile / Ansible
  solidity   — Ethereum smart contracts, EVM patterns, security analysis
  mobile_ui  — React/TSX, Flutter/Dart, SwiftUI, Jetpack Compose
  data_sci   — Python ML/data science (pandas, numpy, sklearn, torch)

Domain detection (task dispatch):
  detect_domain(task_text) → domain name or None (falls back to base BUILDER role)

Usage:
  # Score models on specialist dimensions
  python scripts/determinex_specialist.py --probe sql --models sentinel:latest engineer:latest

  # Detect domain and route a task
  python scripts/determinex_specialist.py --route "Write a SQL query to find the top 10 customers by revenue"

  # Full specialist scorecard
  python scripts/determinex_specialist.py --scorecard --models sentinel:latest

  # Show assignment for all domains given available models
  python scripts/determinex_specialist.py --assign --models sentinel:latest engineer:latest observer:latest
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_LOG = _ROOT / "logs"
_SPEC_OUT = _LOG / "specialist_assignment.json"

# Composite weights — identical to determinex_benchmark.py
LOCAL_WEIGHTS = {"public": 0.3, "micro_eval": 0.5, "calibration": 0.2}
API_WEIGHTS = {"public": 0.8, "api_calibration": 0.2}

COMPILE_TIMEOUT = 25

# ── Specialist domain definitions ─────────────────────────────────────────────

SPECIALIST_DOMAINS = ["sql", "iac", "solidity", "mobile_ui", "data_sci", "powershell"]

# Public leaderboard priors for specialist dimensions.
# Format: {model_family: {domain: score}}
# Source: domain-specific benchmarks (Spider for SQL, HumanEval-X for others),
# community evaluations, April 2026.
DEFAULT_SPECIALIST_PUBLIC: dict[str, dict[str, float]] = {
    "determinex-sentinel": {
        "sql": 0.65,
        "iac": 0.62,
        "solidity": 0.55,
        "mobile_ui": 0.60,
        "data_sci": 0.67,
        "powershell": 0.58,
    },
    "determinex-observer": {
        "sql": 0.58,
        "iac": 0.55,
        "solidity": 0.48,
        "mobile_ui": 0.63,
        "data_sci": 0.61,
        "powershell": 0.52,
    },
    "determinex-engineer": {
        "sql": 0.60,
        "iac": 0.57,
        "solidity": 0.50,
        "mobile_ui": 0.65,
        "data_sci": 0.62,
        "powershell": 0.55,
    },
    # Base families
    "mistral-7b": {
        "sql": 0.64,
        "iac": 0.61,
        "solidity": 0.54,
        "mobile_ui": 0.59,
        "data_sci": 0.66,
        "powershell": 0.57,
    },
    "llama-3.1-8b": {
        "sql": 0.66,
        "iac": 0.63,
        "solidity": 0.56,
        "mobile_ui": 0.62,
        "data_sci": 0.68,
        "powershell": 0.60,
    },
    "qwen2.5-7b": {
        "sql": 0.71,
        "iac": 0.67,
        "solidity": 0.59,
        "mobile_ui": 0.66,
        "data_sci": 0.72,
        "powershell": 0.63,
    },
    "deepseek-coder-v2": {
        "sql": 0.74,
        "iac": 0.70,
        "solidity": 0.61,
        "mobile_ui": 0.64,
        "data_sci": 0.76,
        "powershell": 0.65,
    },
    "phi-3-mini": {
        "sql": 0.58,
        "iac": 0.55,
        "solidity": 0.47,
        "mobile_ui": 0.60,
        "data_sci": 0.62,
        "powershell": 0.50,
    },
    # API
    "claude-3-5-sonnet": {
        "sql": 0.88,
        "iac": 0.86,
        "solidity": 0.82,
        "mobile_ui": 0.87,
        "data_sci": 0.89,
        "powershell": 0.84,
    },
    "claude-3-opus": {
        "sql": 0.90,
        "iac": 0.88,
        "solidity": 0.87,
        "mobile_ui": 0.86,
        "data_sci": 0.91,
        "powershell": 0.87,
    },
    "gemini-1-5-pro": {
        "sql": 0.87,
        "iac": 0.85,
        "solidity": 0.78,
        "mobile_ui": 0.91,
        "data_sci": 0.88,
        "powershell": 0.82,
    },
}

# ── Domain detection ──────────────────────────────────────────────────────────

_DOMAIN_PATTERNS = {
    "sql": re.compile(
        r"\b(sql|select|insert into|update.*set|delete from|create table|"
        r"alter table|stored procedure|query|schema|database|postgres|mysql|"
        r"sqlite|snowflake|bigquery|dbt|orm)\b",
        re.I,
    ),
    "iac": re.compile(
        r"\b(terraform|hcl|kubernetes|k8s|helm|dockerfile|docker.?compose|"
        r"ansible|playbook|aws|gcp|azure|vpc|ec2|s3|lambda|cloud.?function|"
        r"deployment\.yaml|configmap|ingress|service\.yaml|pod)\b",
        re.I,
    ),
    "solidity": re.compile(
        r"\b(solidity|smart.?contract|ethereum|evm|erc.?20|erc.?721|nft|"
        r"defi|reentrancy|gas|wei|gwei|hardhat|foundry|truffle|openzeppelin|"
        r"blockchain|token|wallet|address|mapping|emit|payable)\b",
        re.I,
    ),
    "mobile_ui": re.compile(
        r"\b(react|tsx|jsx|nextjs|flutter|dart|swiftui|jetpack.?compose|"
        r"component|widget|view.?controller|activity|fragment|layout|"
        r"tailwind|css|html|responsive|mobile|ui|frontend|render)\b",
        re.I,
    ),
    "data_sci": re.compile(
        r"\b(pandas|numpy|sklearn|scikit.?learn|matplotlib|seaborn|"
        r"pytorch|tensorflow|keras|jupyter|dataframe|model\.fit|"
        r"train_test_split|accuracy_score|regression|classification|"
        r"clustering|feature|embedding|neural.?network|ml|machine.?learning)\b",
        re.I,
    ),
    "powershell": re.compile(
        r"\b(powershell|pwsh|cmdlet|pscmdlet|"
        r"Get-\w+|Set-\w+|New-\w+|Remove-\w+|Invoke-\w+|"
        r"Write-Host|Write-Output|Write-Error|"
        r"\$env:|param\s*\(|\[CmdletBinding\]|"
        r"active.?directory|azure.?cli|winrm|psremoting|"
        r"Import-Module|Export-Csv|ConvertTo-Json|ConvertFrom-Json|"
        r"ForEach-Object|Where-Object|Select-Object|Sort-Object|"
        r"scheduled.?task|registry|gpo|group.?policy)\b",
        re.I,
    ),
}


def detect_domain(task: str) -> str | None:
    """
    Returns the specialist domain for a task, or None (falls back to BUILDER role).
    Scores all domains, returns the one with the most keyword hits, or None if tied/zero.
    """
    scores: dict[str, int] = {}
    for domain, pattern in _DOMAIN_PATTERNS.items():
        scores[domain] = len(pattern.findall(task))

    if not any(scores.values()):
        return None

    best_domain = max(scores, key=lambda d: scores[d])
    best_score = scores[best_domain]
    second_scores = sorted(scores.values(), reverse=True)

    # Require clear winner (at least 2 hits, at least 1 more than second)
    if best_score < 2:
        return None
    if len(second_scores) > 1 and second_scores[1] >= best_score:
        return None  # tie → fall back to BUILDER

    return best_domain


# ── Calibration probe suites (10 probes per domain) ──────────────────────────

SPECIALIST_PROBES: dict[str, list[dict]] = {
    "sql": [
        {
            "id": "sql_01",
            "lang": "sql",
            "prompt": "Write a SQL query to find the top 5 customers by total order value. Tables: customers(id, name), orders(id, customer_id, amount).",
            "checks": ["SELECT", "JOIN", "GROUP BY", "ORDER BY", "LIMIT"],
        },
        {
            "id": "sql_02",
            "lang": "sql",
            "prompt": "Write SQL to create a users table with id (primary key, auto-increment), email (unique, not null), created_at (timestamp, default now).",
            "checks": ["CREATE TABLE", "PRIMARY KEY", "UNIQUE", "NOT NULL"],
        },
        {
            "id": "sql_03",
            "lang": "sql",
            "prompt": "Write a SQL query using a CTE to find employees whose salary is above the department average.",
            "checks": ["WITH", "AS", "AVG", "WHERE"],
        },
        {
            "id": "sql_04",
            "lang": "sql",
            "prompt": "Write a SQL query to find all products that have never been ordered. Use a LEFT JOIN or NOT EXISTS.",
            "checks": ["LEFT JOIN", "NULL", "OR", "NOT EXISTS"],
        },
        {
            "id": "sql_05",
            "lang": "sql",
            "prompt": "Write an INSERT statement to add a new row to a products table with columns (name, price, category_id, stock).",
            "checks": ["INSERT INTO", "VALUES"],
        },
        {
            "id": "sql_06",
            "lang": "sql",
            "prompt": "Write SQL to add an index on the email column of a users table.",
            "checks": ["CREATE INDEX", "ON"],
        },
        {
            "id": "sql_07",
            "lang": "sql",
            "prompt": "Write a SQL window function query to rank employees by salary within each department.",
            "checks": ["RANK()", "OVER", "PARTITION BY"],
        },
        {
            "id": "sql_08",
            "lang": "sql",
            "prompt": "Write a SQL UPDATE to set all orders older than 90 days to status='archived'.",
            "checks": ["UPDATE", "SET", "WHERE"],
        },
        {
            "id": "sql_09",
            "lang": "sql",
            "prompt": "Write a SQL query to pivot monthly sales data: one row per product, columns for Jan, Feb, Mar.",
            "checks": ["CASE", "WHEN", "SUM", "GROUP BY"],
        },
        {
            "id": "sql_10",
            "lang": "sql",
            "prompt": "Write a stored procedure or function in SQL that takes a customer_id and returns their total spend.",
            "checks": ["PROCEDURE", "FUNCTION", "BEGIN", "RETURN"],
        },
    ],
    "iac": [
        {
            "id": "iac_01",
            "lang": "hcl",
            "prompt": "Write a Terraform resource block to create an AWS S3 bucket named 'determinex-data' with versioning enabled.",
            "checks": ['resource "aws_s3_bucket"', "versioning", "enabled"],
        },
        {
            "id": "iac_02",
            "lang": "yaml",
            "prompt": "Write a Kubernetes Deployment manifest for an nginx container, 3 replicas, port 80, label app=web.",
            "checks": ["apiVersion", "kind: Deployment", "replicas: 3", "containerPort"],
        },
        {
            "id": "iac_03",
            "lang": "dockerfile",
            "prompt": "Write a Dockerfile for a Python 3.11 FastAPI app. Copy requirements.txt, install deps, copy source, expose 8000, run uvicorn.",
            "checks": ["FROM python", "COPY requirements", "RUN pip", "EXPOSE 8000", "CMD"],
        },
        {
            "id": "iac_04",
            "lang": "hcl",
            "prompt": "Write a Terraform provider block for AWS in us-east-1, and a variable block for region with a default.",
            "checks": ["provider", "aws", "region", "variable"],
        },
        {
            "id": "iac_05",
            "lang": "yaml",
            "prompt": "Write a Kubernetes Service manifest of type LoadBalancer to expose port 80 targeting pods with label app=web.",
            "checks": ["kind: Service", "LoadBalancer", "port:", "targetPort", "selector"],
        },
        {
            "id": "iac_06",
            "lang": "yaml",
            "prompt": "Write an Ansible task to install nginx on Ubuntu and ensure it is started and enabled.",
            "checks": ["name:", "apt:", "service:", "state: started", "enabled"],
        },
        {
            "id": "iac_07",
            "lang": "hcl",
            "prompt": "Write a Terraform output block that exports the public IP of an EC2 instance.",
            "checks": ["output", "value", "aws_instance"],
        },
        {
            "id": "iac_08",
            "lang": "yaml",
            "prompt": "Write a Kubernetes ConfigMap named app-config with a key DATABASE_URL set to a placeholder value.",
            "checks": ["kind: ConfigMap", "data:", "DATABASE_URL"],
        },
        {
            "id": "iac_09",
            "lang": "dockerfile",
            "prompt": "Write a multi-stage Dockerfile: first stage builds a Go binary, second stage is a minimal Alpine image that copies and runs the binary.",
            "checks": ["FROM", "AS", "COPY --from", "RUN go build"],
        },
        {
            "id": "iac_10",
            "lang": "hcl",
            "prompt": "Write a Terraform locals block and a resource that references it to define and use a common name prefix.",
            "checks": ["locals", "local.", "resource"],
        },
    ],
    "solidity": [
        {
            "id": "sol_01",
            "lang": "solidity",
            "prompt": "Write a Solidity ERC-20 token contract named DeterminexToken with symbol CTL, 18 decimals, and a mint function restricted to the owner.",
            "checks": ["pragma solidity", "contract", "ERC20", "onlyOwner", "mint"],
        },
        {
            "id": "sol_02",
            "lang": "solidity",
            "prompt": "Write a Solidity function that withdraws all ETH from a contract to the owner. Include the reentrancy guard pattern.",
            "checks": ["nonReentrant", "call{value:", "require", "owner"],
        },
        {
            "id": "sol_03",
            "lang": "solidity",
            "prompt": "Write a Solidity mapping to track token balances and an event for Transfer. Write the transfer function.",
            "checks": ["mapping", "event Transfer", "emit", "require", "balances"],
        },
        {
            "id": "sol_04",
            "lang": "solidity",
            "prompt": "Write a Solidity modifier called onlyOwner that restricts function access to the contract deployer.",
            "checks": ["modifier onlyOwner", "msg.sender", "require", "_; "],
        },
        {
            "id": "sol_05",
            "lang": "solidity",
            "prompt": "Write a Solidity function that accepts ETH payment and emits an event with the sender and amount.",
            "checks": ["payable", "msg.value", "msg.sender", "emit"],
        },
        {
            "id": "sol_06",
            "lang": "solidity",
            "prompt": "Write a Solidity view function to return the current block timestamp and block number.",
            "checks": ["view", "block.timestamp", "block.number", "returns"],
        },
        {
            "id": "sol_07",
            "lang": "solidity",
            "prompt": "Write a Solidity function that uses a checks-effects-interactions pattern to safely send ETH.",
            "checks": ["require", "balances[", "=", "call{value:"],
        },
        {
            "id": "sol_08",
            "lang": "solidity",
            "prompt": "Write a Solidity constructor that sets the owner to msg.sender and emits an Initialized event.",
            "checks": ["constructor", "msg.sender", "owner", "emit"],
        },
        {
            "id": "sol_09",
            "lang": "solidity",
            "prompt": "Write a Solidity function to batch-transfer tokens to multiple recipients in a single transaction.",
            "checks": ["for", "address[]", "uint256[]", "transfer"],
        },
        {
            "id": "sol_10",
            "lang": "solidity",
            "prompt": "Write a Solidity interface for an ERC-20 token with transfer, approve, and allowance functions.",
            "checks": ["interface", "function transfer", "function approve", "function allowance"],
        },
    ],
    "mobile_ui": [
        {
            "id": "mob_01",
            "lang": "typescript",
            "prompt": "Write a React functional component named UserCard that accepts name and email props and renders them in a div with Tailwind classes.",
            "checks": ["React.FC", "interface", "props", "className", "return ("],
        },
        {
            "id": "mob_02",
            "lang": "typescript",
            "prompt": "Write a React hook that fetches data from a URL on mount and returns {data, loading, error}.",
            "checks": ["useState", "useEffect", "fetch(", "loading", "error"],
        },
        {
            "id": "mob_03",
            "lang": "dart",
            "prompt": "Write a Flutter StatelessWidget named PrimaryButton that takes a label string and an onPressed callback.",
            "checks": ["StatelessWidget", "Widget build", "ElevatedButton", "onPressed"],
        },
        {
            "id": "mob_04",
            "lang": "dart",
            "prompt": "Write a Flutter StatefulWidget that displays a counter and increments it on button press.",
            "checks": ["StatefulWidget", "setState", "_counter", "FloatingActionButton"],
        },
        {
            "id": "mob_05",
            "lang": "typescript",
            "prompt": "Write a React form component with controlled inputs for email and password and a submit handler.",
            "checks": ["useState", "onChange", "onSubmit", "input", "value="],
        },
        {
            "id": "mob_06",
            "lang": "typescript",
            "prompt": "Write a React component that renders a list of items from an array prop, using key properly.",
            "checks": ["map(", "key=", "props", "interface", ".tsx"],
        },
        {
            "id": "mob_07",
            "lang": "dart",
            "prompt": "Write a Flutter widget that shows a loading spinner while data is fetching, then displays the result.",
            "checks": ["FutureBuilder", "AsyncSnapshot", "CircularProgressIndicator", "data"],
        },
        {
            "id": "mob_08",
            "lang": "typescript",
            "prompt": "Write a React context provider and a custom hook to consume it for a theme (light/dark).",
            "checks": ["createContext", "useContext", "Provider", "value="],
        },
        {
            "id": "mob_09",
            "lang": "html",
            "prompt": "Write a semantic HTML5 article page with a header, nav, main content section, and footer. No divs for layout.",
            "checks": ["<header>", "<nav>", "<main>", "<article>", "<footer>"],
        },
        {
            "id": "mob_10",
            "lang": "typescript",
            "prompt": "Write a memoized React component using React.memo and useMemo to avoid unnecessary re-renders.",
            "checks": ["React.memo", "useMemo", "useCallback", "deps"],
        },
    ],
    "data_sci": [
        {
            "id": "ds_01",
            "lang": "python",
            "prompt": "Write a Python function that loads a CSV with pandas, drops rows with null values, and returns the cleaned DataFrame.",
            "checks": ["pd.read_csv", "dropna", "DataFrame", "return"],
        },
        {
            "id": "ds_02",
            "lang": "python",
            "prompt": "Write a Python function using scikit-learn to train a logistic regression model and return accuracy on a test set.",
            "checks": ["LogisticRegression", "fit(", "accuracy_score", "train_test_split"],
        },
        {
            "id": "ds_03",
            "lang": "python",
            "prompt": "Write a Python function that normalizes a numpy array to the range [0, 1].",
            "checks": ["import numpy", "min()", "max()", "return"],
        },
        {
            "id": "ds_04",
            "lang": "python",
            "prompt": "Write a Python function that computes and returns a correlation matrix for a pandas DataFrame.",
            "checks": [".corr()", "DataFrame", "return"],
        },
        {
            "id": "ds_05",
            "lang": "python",
            "prompt": "Write a Python function that uses PyTorch to create a simple 2-layer neural network for binary classification.",
            "checks": ["nn.Module", "nn.Linear", "forward", "torch"],
        },
        {
            "id": "ds_06",
            "lang": "python",
            "prompt": "Write a Python function that groups a DataFrame by a column and computes mean and count for each group.",
            "checks": ["groupby", "agg", "mean", "count"],
        },
        {
            "id": "ds_07",
            "lang": "python",
            "prompt": "Write a Python function to perform train/test split, fit a RandomForest, and return feature importances.",
            "checks": [
                "RandomForestClassifier",
                "feature_importances_",
                "fit(",
                "train_test_split",
            ],
        },
        {
            "id": "ds_08",
            "lang": "python",
            "prompt": "Write a Python function that one-hot encodes categorical columns in a pandas DataFrame.",
            "checks": ["pd.get_dummies", "select_dtypes", "object", "return"],
        },
        {
            "id": "ds_09",
            "lang": "python",
            "prompt": "Write a Python function that plots a confusion matrix using matplotlib or seaborn.",
            "checks": ["confusion_matrix", "plt.", "heatmap", "xlabel"],
        },
        {
            "id": "ds_10",
            "lang": "python",
            "prompt": "Write a Python generator function that yields batches of size N from a list.",
            "checks": ["def ", "yield", "range(0,", "batch"],
        },
    ],
    "powershell": [
        {
            "id": "ps_01",
            "lang": "powershell",
            "prompt": "Write a PowerShell function that accepts a -ComputerName parameter and returns the OS version using Get-WmiObject or Get-CimInstance.",
            "checks": [
                "function",
                "param",
                "ComputerName",
                "Get-CimInstance",
                "Win32_OperatingSystem",
            ],
        },
        {
            "id": "ps_02",
            "lang": "powershell",
            "prompt": "Write a PowerShell script that reads a CSV file, filters rows where Status equals 'Active', and exports the result to a new CSV.",
            "checks": ["Import-Csv", "Where-Object", "Status", "Export-Csv"],
        },
        {
            "id": "ps_03",
            "lang": "powershell",
            "prompt": "Write a PowerShell try/catch/finally block that calls a REST API with Invoke-RestMethod and handles errors gracefully.",
            "checks": ["try", "catch", "Invoke-RestMethod", "finally", "Write-Error"],
        },
        {
            "id": "ps_04",
            "lang": "powershell",
            "prompt": "Write a PowerShell script to query Active Directory for all users in a specific OU and export their Name, Email, and Department to CSV.",
            "checks": ["Get-ADUser", "SearchBase", "Select-Object", "Export-Csv"],
        },
        {
            "id": "ps_05",
            "lang": "powershell",
            "prompt": "Write a PowerShell script that uses the Azure CLI (az) or Az module to list all resource groups in a subscription and filter by location.",
            "checks": ["az group list", "Where-Object", "location", "ConvertFrom-Json"],
        },
        {
            "id": "ps_06",
            "lang": "powershell",
            "prompt": "Write a PowerShell function using [CmdletBinding()] that supports -Verbose, -WhatIf, and pipeline input for a file rename operation.",
            "checks": [
                "[CmdletBinding()",
                "SupportsShouldProcess",
                "ValueFromPipeline",
                "Rename-Item",
            ],
        },
        {
            "id": "ps_07",
            "lang": "powershell",
            "prompt": "Write a PowerShell script that uses Invoke-Command to run a script block on a list of remote computers and collects the output.",
            "checks": ["Invoke-Command", "ComputerName", "ScriptBlock", "foreach"],
        },
        {
            "id": "ps_08",
            "lang": "powershell",
            "prompt": "Write a PowerShell script that reads a registry value from HKLM\\SOFTWARE\\MyApp, checks if it exists, and writes a new value.",
            "checks": ["Get-ItemProperty", "HKLM:", "Set-ItemProperty", "Test-Path"],
        },
        {
            "id": "ps_09",
            "lang": "powershell",
            "prompt": "Write a PowerShell script to create a scheduled task that runs a .ps1 script daily at 3am under a service account.",
            "checks": [
                "New-ScheduledTask",
                "ScheduledTaskAction",
                "ScheduledTaskTrigger",
                "Register-ScheduledTask",
            ],
        },
        {
            "id": "ps_10",
            "lang": "powershell",
            "prompt": "Write a PowerShell pipeline that gets all services, filters to Running state, selects Name and DisplayName, then converts to JSON.",
            "checks": ["Get-Service", "Where-Object", "Status", "Select-Object", "ConvertTo-Json"],
        },
    ],
}


# ── Scoring ───────────────────────────────────────────────────────────────────


def _ollama_generate(model: str, prompt: str) -> str:
    import urllib.request

    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 512},
        }
    ).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())["response"]
    except Exception as e:
        return f"[ERROR] {e}"


def score_probe(probe: dict, response: str) -> float:
    """Score a specialist probe response. Returns 0.0–1.0."""
    resp_lower = response.lower()
    checks = probe.get("checks", [])
    if not checks:
        return 0.5
    hits = sum(1 for c in checks if c.lower() in resp_lower)
    return hits / len(checks)


def run_specialist_probes(model_name: str, domain: str) -> float:
    """Run 10-probe suite for a domain. Returns mean score 0.0–1.0."""
    probes = SPECIALIST_PROBES.get(domain, [])
    if not probes:
        return 0.0

    scores = []
    print(f"    Running {len(probes)} {domain} probes on {model_name}...")
    for probe in probes:
        response = _ollama_generate(model_name, probe["prompt"])
        s = score_probe(probe, response)
        scores.append(s)
        print(f"      {probe['id']}: {s:.2f}  ({probe['prompt'][:50]}...)")

    mean = sum(scores) / len(scores)
    print(f"    {domain} specialist score: {mean:.3f}")
    return mean


# ── Model record ──────────────────────────────────────────────────────────────


@dataclass
class SpecialistRecord:
    name: str
    model_type: str  # "local" | "api"
    public_scores: dict[str, float] = field(default_factory=dict)  # domain → score
    probe_scores: dict[str, float] = field(default_factory=dict)  # domain → score
    composite: dict[str, float] = field(default_factory=dict)  # domain → composite

    def compute_composite(self) -> None:
        for domain in SPECIALIST_DOMAINS:
            pub = self.public_scores.get(domain, 0.0)
            prob = self.probe_scores.get(domain, 0.0)
            if self.model_type == "api":
                self.composite[domain] = (
                    API_WEIGHTS["public"] * pub + API_WEIGHTS["api_calibration"] * prob
                )
            else:
                # Treat probe score as micro_eval proxy + calibration combined
                self.composite[domain] = (
                    LOCAL_WEIGHTS["public"] * pub
                    + LOCAL_WEIGHTS["micro_eval"] * prob * 0.7
                    + LOCAL_WEIGHTS["calibration"] * prob * 0.3
                )


def _match_public(name: str) -> dict[str, float]:
    name_l = name.lower()
    for family, scores in DEFAULT_SPECIALIST_PUBLIC.items():
        if family in name_l:
            return scores
    # Unknown model — neutral priors
    return {d: 0.50 for d in SPECIALIST_DOMAINS}


# ── Assignment ────────────────────────────────────────────────────────────────


def assign_specialists(records: list[SpecialistRecord]) -> dict[str, SpecialistRecord]:
    """For each domain, assign the model with the highest composite specialist score."""
    assignment: dict[str, SpecialistRecord] = {}
    for domain in SPECIALIST_DOMAINS:
        best = max(records, key=lambda r: r.composite.get(domain, 0.0))
        assignment[domain] = best
    return assignment


# ── Display ───────────────────────────────────────────────────────────────────


def print_specialist_scorecard(
    records: list[SpecialistRecord],
    assignment: dict[str, SpecialistRecord],
) -> None:
    bar = "=" * 80
    print(f"\n{bar}")
    print("DETERMINEX SPECIALIST SCORECARD")
    print(bar)

    col_w = 12
    header = f"  {'Model':<30}" + "".join(f"{d:>{col_w}}" for d in SPECIALIST_DOMAINS)
    print(f"\n{header}")
    print(f"  {'-' * 78}")
    for r in sorted(records, key=lambda x: max(x.composite.values(), default=0.0), reverse=True):
        row = f"  {r.name:<30}"
        for d in SPECIALIST_DOMAINS:
            row += f"{r.composite.get(d, 0.0):>{col_w}.3f}"
        print(row)

    print(f"\n{'SPECIALIST SLOT ASSIGNMENT':}")
    print(f"  {'Domain':<16} {'Model':<35} {'Score':>8}  {'Math'}")
    print(f"  {'-' * 75}")
    for domain in SPECIALIST_DOMAINS:
        r = assignment[domain]
        s = r.composite.get(domain, 0.0)
        pub = r.public_scores.get(domain, 0.0)
        pb = r.probe_scores.get(domain, 0.0)
        if r.model_type == "api":
            math = f"0.8×{pub:.2f} + 0.2×{pb:.2f}"
        else:
            math = f"0.3×{pub:.2f} + 0.7×{pb:.2f}"
        print(f"  {domain:<16} {r.name:<35} {s:>8.3f}  = {math}")

    print("\n  User can override any specialist assignment.")
    print(f"\n{bar}\n")


def save_assignment(assignment: dict[str, SpecialistRecord]) -> None:
    _LOG.mkdir(parents=True, exist_ok=True)
    out = {
        domain: {"model": r.name, "score": r.composite.get(domain, 0.0)}
        for domain, r in assignment.items()
    }
    _SPEC_OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  [SPECIALIST] Assignment saved → {_SPEC_OUT}")


# ── Route a task ──────────────────────────────────────────────────────────────


def route_task(task: str, assignment_path: Path = _SPEC_OUT) -> dict:
    """
    Detect domain from task text and look up the assigned specialist model.
    Returns {"domain": str|None, "model": str|None, "fallback": bool}.
    """
    domain = detect_domain(task)
    if domain is None:
        return {
            "domain": None,
            "model": None,
            "fallback": True,
            "note": "No specialist domain detected -- use BUILDER role assignment",
        }

    if assignment_path.exists():
        assignment = json.loads(assignment_path.read_text())
        entry = assignment.get(domain)
        if entry:
            return {
                "domain": domain,
                "model": entry["model"],
                "score": entry["score"],
                "fallback": False,
            }

    return {
        "domain": domain,
        "model": None,
        "fallback": True,
        "note": f"Specialist {domain} detected but no assignment file found. Run --assign first.",
    }


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Determinex specialist slot routing")
    parser.add_argument(
        "--probe",
        type=str,
        choices=SPECIALIST_DOMAINS,
        help="Run calibration probes for one domain against --models",
    )
    parser.add_argument(
        "--scorecard", action="store_true", help="Run full specialist scorecard across all domains"
    )
    parser.add_argument(
        "--assign", action="store_true", help="Run probes and save specialist assignment JSON"
    )
    parser.add_argument(
        "--route",
        type=str,
        metavar="TASK",
        help="Detect domain from task text and print routed model",
    )
    parser.add_argument(
        "--models", nargs="+", default=[], help="Ollama model names to score (e.g. sentinel:latest)"
    )
    parser.add_argument(
        "--list-domains",
        action="store_true",
        help="List all specialist domains and their detection keywords",
    )
    args = parser.parse_args()

    if args.list_domains:
        print("\nSpecialist domains:")
        for domain, pattern in _DOMAIN_PATTERNS.items():
            print(f"  {domain:<14} — {pattern.pattern[:80]}")
        return

    if args.route:
        result = route_task(args.route)
        print(json.dumps(result, indent=2))
        return

    if not args.models and (args.probe or args.scorecard or args.assign):
        print("[ERROR] --models required for probe/scorecard/assign")
        sys.exit(1)

    # Build records
    records = []
    for name in args.models:
        is_api = any(k in name.lower() for k in ["claude", "gemini", "gpt"])
        r = SpecialistRecord(
            name=name,
            model_type="api" if is_api else "local",
            public_scores=_match_public(name),
        )
        records.append(r)

    # Run probes
    domains_to_probe = (
        [args.probe]
        if args.probe
        else SPECIALIST_DOMAINS
        if (args.scorecard or args.assign)
        else []
    )

    for r in records:
        for domain in domains_to_probe:
            if r.model_type == "local":
                r.probe_scores[domain] = run_specialist_probes(r.name, domain)
            else:
                print(f"  [API] Skipping live probes for {r.name} — using public priors only")
                r.probe_scores[domain] = r.public_scores.get(domain, 0.5)
        r.compute_composite()

    if records:
        assignment = assign_specialists(records)
        print_specialist_scorecard(records, assignment)
        if args.assign:
            save_assignment(assignment)


if __name__ == "__main__":
    main()
