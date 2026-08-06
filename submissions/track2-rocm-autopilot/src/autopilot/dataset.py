"""Load the confidential-drafting benchmark prompts.

The suite simulates the workload class that justifies local inference:
producing confidential documents (patent claims, medical reports,
anonymized articles) from raw notes. Long context in, long structured
text out: it stresses KV cache and batching far better than random tokens.
"""

import json


def load_prompts(path: str) -> list[str]:
    with open(path) as f:
        return [json.loads(line)["prompt"] for line in f if line.strip()]
