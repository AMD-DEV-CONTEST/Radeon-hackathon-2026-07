import os
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup

load_dotenv()

guardian_key = os.getenv("GUARDIAN_KEY")


def get_snippet(snippet_url):
    res = requests.get(f"{snippet_url}?show-fields=body&api-key={guardian_key}")

    data = res.json()
    body_html = data["response"]["content"]["fields"]["body"]
    soup = BeautifulSoup(body_html, "html.parser")
    text_blocks = []
    for tag in soup.find_all(["p", "h2"]):
        text_blocks.append(tag.get_text(separator=" ", strip=True))

    clean_text = "\n\n".join(text_blocks)
    return clean_text


def get_news(topic="ai"):
    res = requests.get(
        f"https://content.guardianapis.com/search?q={topic}&api-key={guardian_key}"
    )
    news_list = res.json()["response"]["results"]
    headlines = []
    for news in news_list:
        headlines.append(news["webTitle"])
    for news in news_list:
        web_title = news["webTitle"]
        snippet_url = news["apiUrl"]
        snippet = get_snippet(snippet_url)
        formatted = f"--- {web_title} ---\n{snippet}"
        print(formatted)
        return headlines, formatted
