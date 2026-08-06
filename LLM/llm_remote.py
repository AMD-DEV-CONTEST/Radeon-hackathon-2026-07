import requests
import os

class LLM_Remote:
    def __init__(self):
        self.api_key: str = os.getenv("API_KEY") or ""
        self.base_url: str = os.getenv("BASE_URL") or ""

        if self.api_key == "":
            raise ValueError("API_KEY is not set in the environment variables.")
        if self.base_url == "":
            raise ValueError("BASE_URL is not set in the environment variables.")

        if self.base_url.endswith("/"):
            self.base_url = self.base_url[:-1]

        if not self.base_url.endswith("/chat/completions"):
            self.base_url += "/chat/completions"

    def _call_api(self, prompt: str, system_instruction: str) -> tuple[int, dict]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        data = {
            #"model": "Qwen3.6-35B-A3B",
            "model": "accounts/fireworks/models/kimi-k2p7-code",
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ]
        }

        api_response = requests.post(self.base_url, headers=headers, json=data)

        return api_response.status_code, api_response.json()

    def generate(self, prompt: str, system_instruction: str, number_of_attempts: int, temperature: float, max_tokens: int) -> str:
        response = ""
        response_generated = False

        for attempt in range(number_of_attempts):
            status_code, api_response = self._call_api(prompt, system_instruction)

            if status_code == 200:
                response = api_response.get("choices", [{}])[0].get("message", {}).get("content", "")
                response_generated = True

                break

        if not response_generated:
            raise Exception(f"Failed to generate response after {number_of_attempts} attempts. Last status code: {status_code}, response: {api_response}")

        return response