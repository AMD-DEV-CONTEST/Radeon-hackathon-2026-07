"""Async Code Optimizer & Review Agent.

Ready-to-run demo for the live AMD Radeon Cloud vLLM endpoint.
It uses the standard OpenAI-compatible async client, so it starts fast on
Windows and avoids CrewAI's heavy import/logging overhead.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from textwrap import dedent

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI


RADEON_CLOUD_BASE_URL = "https://radeon-global.anruicloud.com/spaces/u-13774-60d1b47b/8000/v1"
RADEON_CLOUD_API_KEY = "sk-e63485ad8f8f796132c8650e888f5598af520ac4"
MODEL_NAME = "Qwen/Qwen2-7B-Instruct"


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


SAMPLE_BAD_PYTHON_CODE = dedent(
    """
    def top_k_frequent_numbers(nums, k):
        result = []
        counts = {}

        for n in nums:
            if n in counts:
                counts[n] = counts[n] + 1
            else:
                counts[n] = 1

        # Bad: repeatedly scans all keys, mutates counts, and breaks when k is
        # larger than the number of unique values.
        for i in range(k):
            best_number = None
            best_count = -1
            for number in counts:
                if counts[number] > best_count:
                    best_number = number
                    best_count = counts[number]

            result.append(best_number)
            del counts[best_number]

        return result


    values = [4, 1, 2, 2, 3, 3, 3, 4, 4, 4]
    print(top_k_frequent_numbers(values, 3))
    """
).strip()


@dataclass(frozen=True)
class RadeonCloudConfig:
    base_url: str = RADEON_CLOUD_BASE_URL
    api_key: str = RADEON_CLOUD_API_KEY
    model: str = MODEL_NAME
    temperature: float = 0.15
    timeout_seconds: float = 180.0


@dataclass(frozen=True)
class AsyncCodeAgent:
    name: str
    system_prompt: str
    client: AsyncOpenAI
    config: RadeonCloudConfig

    async def run(self, user_prompt: str) -> str:
        print(f"{self.name}: running...")
        response = await self.client.chat.completions.create(
            model=self.config.model,
            temperature=self.config.temperature,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        return (content or "").strip()


def build_client(config: RadeonCloudConfig) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=config.base_url,
        api_key=config.api_key,
        timeout=config.timeout_seconds,
    )


async def check_server_connection(config: RadeonCloudConfig) -> None:
    headers = {"Authorization": f"Bearer {config.api_key}"}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{config.base_url}/models", headers=headers)
        response.raise_for_status()


async def run_async_workflow(source_code: str) -> str:
    config = RadeonCloudConfig()
    client = build_client(config)

    reviewer_agent = AsyncCodeAgent(
        name="Reviewer Agent",
        system_prompt=(
            "You are a senior AI code-review engineer. Review Python code for "
            "correctness bugs, edge cases, algorithmic complexity, avoidable "
            "allocations, and latency bottlenecks. Be concrete and concise."
        ),
        client=client,
        config=config,
    )

    optimizer_agent = AsyncCodeAgent(
        name="Optimizer Agent",
        system_prompt=(
            "You are a performance-focused software engineer. Rewrite Python code "
            "into a correct, readable, low-latency implementation. Preserve intended "
            "behavior, fix proven bugs, and explain changes briefly."
        ),
        client=client,
        config=config,
    )

    print("Connecting to AMD Radeon Cloud vLLM endpoint...")
    print(f"Base URL: {config.base_url}")
    print(f"Model: {config.model}")
    await check_server_connection(config)
    print("Connection check passed.\n")

    review_prompt = dedent(
        f"""
        Review this Python code for correctness and performance.

        Return exactly these sections:
        1. Correctness issues
        2. Performance bottlenecks
        3. Required behavior to preserve
        4. Rewrite strategy

        Code:
        ```python
        {source_code}
        ```
        """
    ).strip()

    review_text = await reviewer_agent.run(review_prompt)
    print("Reviewer Agent: done.\n")

    optimizer_prompt = dedent(
        f"""
        Use the review below to produce a complete optimized replacement.

        Requirements:
        - Return runnable Python code.
        - Preserve intended output for valid inputs.
        - For this sample, the expected output is [4, 3, 2].
        - Sort primarily by descending frequency.
        - If frequencies tie, preserve the first-seen order from the input list.
        - Handle k larger than the number of unique values.
        - Improve avoidable repeated scans or unnecessary mutations.
        - Do not reverse the final top-k list unless the original behavior requires it.
        - After the code, add a short "Why this is better" section.

        Original code:
        ```python
        {source_code}
        ```

        Reviewer Agent findings:
        {review_text}
        """
    ).strip()

    optimized_output = await optimizer_agent.run(optimizer_prompt)
    print("Optimizer Agent: done.")
    return optimized_output


async def main_async() -> None:
    print("=== Async Code Optimizer & Review Agent ===\n")
    print("=== Input Code ===\n")
    print(SAMPLE_BAD_PYTHON_CODE)
    print()

    try:
        optimized_output = await run_async_workflow(SAMPLE_BAD_PYTHON_CODE)
    except httpx.HTTPStatusError as exc:
        print("Remote vLLM endpoint returned an HTTP error.")
        print(f"Status code: {exc.response.status_code}")
        print(f"Response: {exc.response.text[:500]}")
        return
    except (httpx.RequestError, APIConnectionError, APITimeoutError) as exc:
        print("Could not connect to the AMD Radeon Cloud vLLM endpoint.")
        print(f"Details: {exc}")
        return
    except APIStatusError as exc:
        print("The remote model API returned an error.")
        print(f"Status code: {exc.status_code}")
        print(f"Response: {exc.response.text[:500]}")
        return
    except Exception as exc:
        print("The async agent workflow failed.")
        print(f"Details: {exc}")
        return

    print("\n=== Final Optimized Output ===\n")
    print(optimized_output)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
