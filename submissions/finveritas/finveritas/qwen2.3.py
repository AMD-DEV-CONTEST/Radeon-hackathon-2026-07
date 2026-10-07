import requests
import json

url = "http://localhost:1234/v1/chat/completions"

headers = {
    "Content-Type": "application/json"
}

payload = {
    "model": "local-model",
    "messages": [
        {
            "role": "system",
            "content": "You are an explainable AI assistant. Do not make decisions."
        },
        {
            "role": "user",
            "content": (
                "Company: HCL Technologies\n"
                "Revenue: Declining\n"
                "Cash Flow: Decreasing\n"
                "Liabilities: Increasing\n"
                "Action: Loan blocked by guardrails\n\n"
                "Explain this outcome clearly."
            )
        }
    ],
    "temperature": 0.2
}

response = requests.post(url, headers=headers, json=payload)

print(response.status_code)
print(response.json()["choices"][0]["message"]["content"])
