"""ImageAgent — diary image enrichment orchestrator.

Runs in the diary `.venv` (the SAME env as :class:`DiaryAgent`). It is a *separate
concern* from the text interviewer: it reads a day's graph data, composes
English T2I prompts (translating the user's Chinese diary text), calls the resident
Z-Image-Turbo service over HTTP, asks the 35B vision LLM (``:8089`` + mmproj) to
critique each image, and writes a per-day manifest.

CRITICAL cross-env rule: this module NEVER imports ai-toolkit / diffusers. It only
talks HTTP to the image service (``IMAGE_SERVICE_URL``) and to the judge (``:8089``).
"""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any, Optional

import requests
from openai import OpenAI

from diary import config
from diary import runtime
from diary import schema as S
from diary.tools import DiaryContext

# Visual subjects worth a thumbnail. Food/Place/Activity are the headline cases
# from the user's request; the rest are also concretely imageable.
VISUAL_LABELS = {
    S.L_FOOD, S.L_MEAL, S.L_PLACE, S.L_ACTIVITY, S.L_CLOTHING,
    S.L_SHELTER, S.L_TRANSPORT, S.L_EVENT, S.L_THING,
}

IMAGE_SERVICE_URL = os.getenv("IMAGE_SERVICE_URL", "http://127.0.0.1:8090")
MEDIA_ROOT = os.getenv("DIARY_MEDIA_ROOT", os.path.join(os.path.dirname(__file__), "..", "media"))

# Generation sizes are deliberately small to conserve VRAM: the shared GPU also
# hosts the ~21 GiB llama-server, so every image step competes for the same
# memory. Thumbnails are only ever shown small (graph nodes / gallery grid), so
# 512px is plenty; the poster stays 768px for a decent day-summary image.
POSTER_W, POSTER_H = 768, 768
THUMB_W, THUMB_H = 512, 512
COMIC_W, COMIC_H = 896, 512

COMPOSE_SYSTEM = """You turn a personal voice-diary into image-generation prompts for
Z-Image-Turbo (a model trained on ENGLISH captions). You will be given diary text
(possibly in Chinese) and the entities the user mentioned.

Rules:
- ALWAYS write the image prompt in ENGLISH, rich with scene/lighting/mood/details.
- CRITICAL — NO TEXT IN THE IMAGE: the prompt must NEVER ask for any text, letters,
  words, typography, captions, headlines, banners, signs, logos, or lettering to be
  rendered in the image — in ANY language, especially NO Chinese characters.
  Z-Image renders text as garbled marks, so the image must be a pure illustration
  with zero written text.
- Preserve the user's described details (what food, which place, the activity, the
  weather, who was there). Do NOT invent new facts.
- Keep it a single cohesive illustration, not a collage, unless asked.
- Respond with ONLY a JSON object, no prose. All fields ('prompt', 'summary',
  'highlights', 'caption') must be written in ENGLISH.
"""

POSTER_USER = """Summarize this day as ONE poster-like illustration. Return JSON:
{"prompt": "<english T2I prompt for a beautiful day-summary poster — pure illustration, NO text/lettering>",
 "summary": "<3-6 word ENGLISH headline capturing the day's vibe>",
 "highlights": ["<one short ENGLISH highlight>", ...]  # 3-5 bullets, all in English}
Diary entries:
<<ENTRIES>>
"""

THUMB_USER = """The user described a specific subject worth a picture. Return JSON:
{"prompt": "<english T2I prompt focusing on this subject, including the details given — pure illustration, NO text/lettering>",
 "caption": "<short ENGLISH caption naming the subject>"}
Subject entity: <<SUBJECT>> (<<LABEL>>)
Surrounding diary text: <<CONTEXT>>
"""

COMIC_USER = """Pick <<N>> distinct story beats from this day and turn each into a comic
panel. Return JSON: {"panels": [{"prompt": "<english T2I prompt for the panel scene — pure illustration, NO text/lettering>",
"caption": "<short ENGLISH caption>"}]}
Diary entries:
<<ENTRIES>>
"""

JUDGE_SYSTEM = """You are a careful image critic for a personal diary app. You are shown
a generated image and the user's original description of that moment. In 2-3 short
sentences IN ENGLISH, say: (1) does the image match what the user described,
(2) any obvious quality problems (extra limbs, deformed faces, wrong subject,
blurry, garbled text in the image). Be concise and kind. Do not invent praise."""


# ─── graph read (entries + their mentions) ────────────────────────────────


def read_day_rich(ctx: DiaryContext, date: str) -> list[dict]:
    """Return the day's entries with their linked mention facets.

    Differs from :func:`diary.tools.read_day` (text only) — we need per-entry
    mentions to decide which moments are imageable and to seed the prompts.
    """
    client = ctx.client
    day_id = S.ensure_day(client, date)
    reached = client.gremlin(
        [{"step": "V", "ids": [day_id]}, {"step": "out", "name": S.E_HAS_ENTRY, "depth": 1}]
    ) or []
    entries = [v for v in reached if S.L_ENTRY in (v.get("labels") or [])]
    out = []
    for e in entries:
        props = e.get("properties") or {}
        text = props.get("text", "")
        if not text:
            continue
        mreached = client.gremlin(
            [{"step": "V", "ids": [e["id"]]}, {"step": "out", "name": S.E_MENTIONS, "depth": 1}]
        ) or []
        mentions = [
            {
                "label": (v.get("labels") or [S.L_THING])[0],
                "key": (v.get("properties") or {}).get("key")
                or (v.get("name") or "").split(":", 1)[-1],
                "properties": v.get("properties") or {},
            }
            for v in mreached
            if v.get("type") == "vertex"
        ]
        out.append(
            {
                "id": e["id"],
                "text": text,
                "ts": props.get("ts"),
                "lang": props.get("lang", "zh"),
                "mentions": mentions,
            }
        )
    return out


# ─── ImageAgent ───────────────────────────────────────────────────────────


class ImageAgent:
    def __init__(self, service_url: str = IMAGE_SERVICE_URL, judge_base_url: str | None = None):
        self.service_url = service_url
        self._client: Optional[OpenAI] = None
        self._judge_base_url = judge_base_url or config.LLM_BASE_URL

    # -- LLM helper -------------------------------------------------------
    def _llm(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(api_key=config.LLM_API_KEY, base_url=self._judge_base_url)
        return self._client

    def _chat(self, messages: list[dict], max_tokens: int = 600, temperature: float = 0.6):
        """LLM call with thinking DISABLED (Qwen3.6 thinks by default and would
        burn max_tokens on reasoning, returning empty/truncated JSON). Mirrors
        DiaryAgent's toggle, with a retry if the server rejects the flag.
        """
        kwargs = {
            "model": config.LLM_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        }
        try:
            return self._llm().chat.completions.create(**kwargs)
        except Exception:
            kwargs.pop("extra_body", None)
            return self._llm().chat.completions.create(**kwargs)

    def _llm_json(self, system: str, user: str, max_tokens: int = 600) -> dict:
        try:
            resp = self._chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
            )
            return _parse_json(resp.choices[0].message.content or "")
        except Exception as e:  # never block image generation on a compose failure
            import logging
            logging.getLogger("image_agent").warning("compose LLM failed: %s", e)
            return {}

    # -- composition ------------------------------------------------------
    def compose_day_poster(self, entries: list[dict]) -> dict:
        text = "\n".join(f"- {e['text']}" for e in entries)
        data = self._llm_json(COMPOSE_SYSTEM, POSTER_USER.replace("<<ENTRIES>>", text), max_tokens=900)
        return {
            "prompt": data.get("prompt", "a warm illustrated summary of a personal day"),
            "summary": data.get("summary", ""),
            "highlights": data.get("highlights", []),
        }

    def compose_thumbnail(self, entry: dict, subject: dict) -> dict:
        data = self._llm_json(
            COMPOSE_SYSTEM,
            THUMB_USER.replace("<<SUBJECT>>", subject.get("key", ""))
            .replace("<<LABEL>>", subject.get("label", ""))
            .replace("<<CONTEXT>>", entry["text"]),
        )
        return {
            "prompt": data.get("prompt", f"an illustration of {subject.get('key', 'a moment')}"),
            "caption": data.get("caption", subject.get("key", "")),
        }

    def compose_comic(self, entries: list[dict], n: int = 3) -> list[dict]:
        text = "\n".join(f"- {e['text']}" for e in entries)
        data = self._llm_json(
            COMPOSE_SYSTEM, COMIC_USER.replace("<<N>>", str(n)).replace("<<ENTRIES>>", text)
        )
        return data.get("panels", [])[:n]

    # -- image service ----------------------------------------------------
    def _gen_image(self, prompt: str, out_path: str, seed: int, w: int, h: int) -> Optional[bytes]:
        """Call the resident Z-Image service. Returns PNG bytes or None on failure.

        The service writes to ``out_path`` itself and skips if it already exists, but
        we also persist the response so the local file is always present afterwards.
        """
        try:
            resp = requests.post(
                f"{self.service_url}/generate",
                json={"prompt": prompt, "w": w, "h": h, "seed": seed, "out": out_path},
                timeout=180,
            )
        except Exception as e:
            import logging
            logging.getLogger("image_agent").warning("image service unreachable: %s", e)
            return None
        if resp.status_code != 200:
            import logging
            logging.getLogger("image_agent").warning("image service error %s: %s",
                                                      resp.status_code, resp.text[:200])
            return None
        data = resp.content
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(data)
        return data

    # -- judge (35B vision) ----------------------------------------------
    def judge(self, image_bytes: bytes, story_text: str) -> str:
        if not image_bytes:
            return ""
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        messages = [
            {"role": "system", "content": JUDGE_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"User's description:\n{story_text}"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            },
        ]
        try:
            resp = self._chat(messages, max_tokens=300, temperature=0.4)
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            import logging
            logging.getLogger("image_agent").warning("judge failed: %s", e)
            return ""

    # -- decision helpers -------------------------------------------------
    @staticmethod
    def should_generate_thumbnail(entry: dict) -> bool:
        """True when the entry has >=1 concretely imageable subject mention."""
        return any(m.get("label") in VISUAL_LABELS for m in entry.get("mentions", []))

    # -- orchestration ----------------------------------------------------
    def generate_for_day(
        self,
        date: str,
        ctx: DiaryContext,
        force: bool = False,
        with_comic: bool = False,
    ) -> Optional[list[dict]]:
        """Generate poster + thumbnails (+ optional comic) for a day.

        Idempotent: returns the existing manifest unless ``force``. Writes
        ``media/<date>/manifest.json``. Returns the manifest list, or None if the
        day has no entries to illustrate.
        """
        day_dir = os.path.join(MEDIA_ROOT, date)
        manifest_path = os.path.join(day_dir, "manifest.json")
        if not force and os.path.isfile(manifest_path):
            with open(manifest_path, encoding="utf-8") as f:
                return json.load(f)

        entries = read_day_rich(ctx, date)
        entries = [e for e in entries if e["text"].strip()]
        if not entries:
            return None

        manifest: list[dict] = []
        base_seed = 1000 + abs(hash(date)) % 100000

        # Day poster
        poster = self.compose_day_poster(entries)
        out = os.path.join(day_dir, "poster.png")
        img = self._gen_image(poster["prompt"], out, base_seed, POSTER_W, POSTER_H)
        if img:  # only record a manifest entry for images that were actually written
            critique = self.judge(img, "\n".join(e["text"] for e in entries))
            manifest.append({
                "type": "poster",
                "seed": base_seed,
                "prompt": poster["prompt"],
                "image_path": out,
                "summary": poster["summary"],
                "highlights": poster["highlights"],
                "judge_critique": critique,
                "linked_entry_ids": [e["id"] for e in entries],
            })

        # Thumbnails for imageable moments
        for i, entry in enumerate(entries):
            if not self.should_generate_thumbnail(entry):
                continue
            subjects = [m for m in entry["mentions"] if m.get("label") in VISUAL_LABELS]
            subject = subjects[0]
            thumb = self.compose_thumbnail(entry, subject)
            out = os.path.join(day_dir, f"thumb_{entry['id']}.png")
            seed = base_seed + 10 + i
            img = self._gen_image(thumb["prompt"], out, seed, THUMB_W, THUMB_H)
            if not img:
                continue  # generation failed — do NOT reference a file that doesn't exist
            critique = self.judge(img, entry["text"])
            manifest.append({
                "type": "thumb",
                "seed": seed,
                "prompt": thumb["prompt"],
                "image_path": out,
                "caption": thumb["caption"],
                "subject": subject.get("key"),
                "judge_critique": critique,
                "linked_entry_ids": [entry["id"]],
            })

        # Optional comic (Phase B)
        if with_comic:
            panels = self.compose_comic(entries, n=3)
            for i, panel in enumerate(panels):
                out = os.path.join(day_dir, f"comic_{i}.png")
                seed = base_seed + 100 + i
                img = self._gen_image(panel.get("prompt", ""), out, seed, COMIC_W, COMIC_H)
                if not img:
                    continue
                manifest.append({
                    "type": "comic",
                    "seed": seed,
                    "prompt": panel.get("prompt", ""),
                    "image_path": out,
                    "caption": panel.get("caption", ""),
                    "judge_critique": self.judge(img, panel.get("caption", "")),
                    "linked_entry_ids": [e["id"] for e in entries],
                })

        os.makedirs(day_dir, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return manifest


def _parse_json(raw: str) -> dict:
    if not raw:
        return {}
    text = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
