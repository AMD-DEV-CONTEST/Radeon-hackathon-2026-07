"""
llm_service.py - OpenAI-compatible LLM connection and helper functions.
"""

import json
from openai import OpenAI
from typing import Type, TypeVar
from pydantic import BaseModel, ValidationError
from config import OPENAI_BASE_URL, OPENAI_API_KEY, MODEL_NAME

T = TypeVar('T', bound=BaseModel)

# Initialize a client for any OpenAI-compatible endpoint.
client = OpenAI(
    base_url=OPENAI_BASE_URL,
    api_key=OPENAI_API_KEY,
)


def generate_text(system_prompt: str, user_prompt: str) -> str:
    """
    Standard unstructured chat completion.
    """
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2
        )
        return response.choices[0].message.content
    except Exception as e:
        raise RuntimeError(
            f"LLM request failed: {e}\n"
            f"Make sure the OpenAI-compatible endpoint is available at "
            f"{OPENAI_BASE_URL} with model '{MODEL_NAME}'."
        )


def generate_structured(system_prompt: str, user_prompt: str, schema_class: Type[T]) -> T:
    """
    Enforces JSON schema output compatible with Pydantic model validation.
    """
    schema_json = json.dumps(schema_class.model_json_schema(), indent=2)

    full_system_prompt = f"""{system_prompt}

CRITICAL: You MUST respond using ONLY valid JSON that strictly adheres to this JSON schema:
{schema_json}
Do not wrap your output in markdown backticks or extra commentary. Return raw JSON only."""

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": full_system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1
        )

        raw_content = response.choices[0].message.content
        return schema_class.model_validate_json(raw_content)
    except ValidationError as ve:
        raise ValueError(
            f"LLM returned JSON that does not match the expected schema ({schema_class.__name__}): {ve}"
        )
    except Exception as e:
        raise RuntimeError(
            f"Structured LLM request failed: {e}\n"
            f"Make sure the OpenAI-compatible endpoint is available at "
            f"{OPENAI_BASE_URL} with model '{MODEL_NAME}'."
        )


def check_connection() -> bool:
    """Verify that the configured OpenAI-compatible endpoint is reachable."""
    try:
        client.models.list()
        return True
    except Exception:
        return False
