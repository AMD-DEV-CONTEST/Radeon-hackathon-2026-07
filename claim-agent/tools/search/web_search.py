import requests
import json

def web_search(query, num_results=5):
    url = "https://mcp.exa.ai/mcp"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"
    }
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "web_search_exa",
            "arguments": {
                "query": query,
                "numResults": num_results
            }
        }
    }

    response = requests.post(url, json=payload, headers=headers, timeout=30)
    response.encoding = 'utf-8'  # 关键：设置编码

    if response.status_code == 200:
        for line in response.text.split('\n'):
            if line.startswith('data: '):
                data = json.loads(line[6:])
                if 'result' in data:
                    for content in data['result']['content']:
                        if content['type'] == 'text':
                            return content['text']
    return None

if __name__ == "__main__":
    query = input("输入搜索内容: ")
    result = web_search(query)
    if result:
        print("\n" + result)
