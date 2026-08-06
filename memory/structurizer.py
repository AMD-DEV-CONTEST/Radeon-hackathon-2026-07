"""Text-to-graph structurization and graph-to-text regeneration using LLM.

Extraction: raw text → structured entities, events, phases, relationships
Regeneration: graph data → narrative prose
Chunking: splits long texts (>1500 chars) into sliding windows with state passing
"""

import json
import logging
import re
from pathlib import Path

from openai import OpenAI

from config.settings import QWEN_API_KEY, QWEN_BASE_URL, QWEN_LLM_MODEL
from utils.timing import timing

logger = logging.getLogger(__name__)

# Safe text size for Qwen API (prevents timeouts)
MAX_CHUNK_CHARS = 900
CHUNK_OVERLAP = 100

# Log directory for extraction audit trail
_LOG_DIR = Path(__file__).parent.parent / "log"


def _log_extraction(data: dict, tag: str = "extraction"):
    """Save extraction result as timestamped JSON for debugging/audit."""
    try:
        import time as _time

        _LOG_DIR.mkdir(exist_ok=True)
        ts = _time.strftime("%Y%m%d_%H%M%S")
        path = _LOG_DIR / f"{tag}-{ts}.json"
        import json as _json

        path.write_text(_json.dumps(data, indent=2, ensure_ascii=False))
        logger.debug("Logged extraction: %s (%d entities)", path, len(data.get("entities", [])))
    except Exception as e:
        logger.debug("Logging failed: %s", e)


EXTRACTION_SYSTEM = """You are a narrative structuring expert. Extract structured data from text.

IMPORTANT: Entity names MUST be exact words/phrases from the text. Do NOT paraphrase or embellish names. If the text says "小林", use "小林" not "小林女士" or "小林小姐".

## Entity Types
person: individual (e.g. "Einstein", "his mother")
object: physical artifact with significance (e.g. "typewriter", "a worn hat")
place: location (e.g. "Princeton", "the basement lab")
concept: abstract idea (e.g. "freedom", "legacy")
skill: ability or craft (e.g. "violin", "carpentry")
trait: personality quality (e.g. "stubbornness", "quiet determination")
body_part: body part with narrative weight (e.g. "injured knee")
feeling: emotional state (e.g. "regret", "hope")

## Relationship Types
parent_of, child_of, married, friend_of, mentor_of, colleague_of, rival_of
has_trait (person → trait)
masters, creates, builds, uses (person → skill/object)
birthplace_of, educated_at, works_at, lived_at, visited (place → person or reverse)
owns, writes, receives, loses, finds (person → object)
SYMBOLIZES (entity → concept)

## Event Properties
Each event needs: label (short), description (1-2 sentences), order (integer), time_period (year/age/era)
Events must have participants with roles: "主体", "参与者", "对象", "地点", "关键设备", "成果"

## Phases
Group events into 3-7 life phases with label and description.

## Causal Links
Connect events where one causes another: from_event, to_event, context

Return ONLY a JSON object with this structure:
{
  "title": "story title",
  "entities": [{"name": "...", "type": "...", "description": "..."}],
  "events": [{"label": "...", "description": "...", "order": 1, "time_period": "...", "participants": [{"entity": "...", "role": "..."}]}],
  "phases": [{"label": "...", "description": "...", "order": 1, "events": ["event_label_1", "event_label_2"]}],
  "relationships": [{"from": "...", "to": "...", "type": "...", "context": ""}],
  "causal_links": [{"from": "...", "to": "...", "context": ""}],
  "symbols": [{"entity": "...", "concept": "...", "context": ""}]
}

IMPORTANT:
- Entity names must be unique and descriptive
- Cover ALL key events, not just the first few
- Include conceptual/symbolic depth in symbols
- Map characters to their traits
- Find causal chains between events
"""

REGENERATION_SYSTEM = """You are a narrative reconstruction expert. Given structured graph data about a person's life, reconstruct a flowing, emotionally resonant biography in natural {}.

## Rules
1. Start with a compelling opening sentence
2. Follow the phases and events in order
3. Weave in character traits naturally (don't list them)
4. Show causal connections between events
5. End with the symbolic meaning of key objects
6. Keep under 800 words
7. Write in a warm, literary style
8. Do NOT use markdown formatting, just plain paragraphs

Given the structured data below, write the biography:"""


@timing(name="structurize")
def structurize_text(text: str) -> dict:
    """Extract structured graph data from raw text using LLM.

    Returns a dict compatible with StoryGraphBuilder.
    """
    if not QWEN_API_KEY or QWEN_API_KEY == "your_qwen_api_key_here":
        raise RuntimeError("No Qwen API key configured")

    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

    # Truncate text if too long (roughly 4000 tokens)
    if len(text) > 8000:
        text = text[:8000] + "\n...(truncated)"

    resp = client.chat.completions.create(
        model=QWEN_LLM_MODEL,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM},
            {"role": "user", "content": f"Extract structured data from this biography:\n\n{text}"},
        ],
        temperature=0.1,
        max_tokens=6000,
    )

    raw = resp.choices[0].message.content.strip()
    # Clean markdown fences
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n", "", raw)
        raw = re.sub(r"\n```$", "", raw)

    try:
        data = json.loads(raw)
        _log_extraction(data, "extraction")
        return data
    except json.JSONDecodeError as e:
        logger.warning("JSON parse failed at pos %s, trying recovery", e.pos)
        # Try fixing common issues:
        # 1. Truncated near end - try to close braces
        fixed = _try_fix_truncated_json(raw)
        if fixed:
            try:
                data = json.loads(fixed)
                _log_extraction(data, "extraction_recovered")
                return data
            except json.JSONDecodeError:
                pass
        # 2. Try extracting JSON block
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            _log_extraction(data, "extraction_block")
            return data
        # 3. Try fixing at the error position
        pos = e.pos
        fixed = raw[:pos] + raw[pos:].replace("\n", " ").replace('"', '\\"')
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            raise


def _try_fix_truncated_json(text: str) -> str | None:
    """Try to fix truncated JSON by counting and closing braces/brackets."""
    stack = []
    i = 0
    in_string = False
    escape = False
    for c in text:
        if escape:
            escape = False
            i += 1
            continue
        if c == "\\":
            escape = True
        elif c == '"' and not escape:
            in_string = not in_string
        elif not in_string:
            if c in "{[":
                stack.append(c)
            elif c == "}":
                if stack and stack[-1] == "{":
                    stack.pop()
            elif c == "]":
                if stack and stack[-1] == "[":
                    stack.pop()
        i += 1

    if not stack:
        return None

    # Build closing characters
    closing = ""
    for c in reversed(stack):
        closing += "}" if c == "{" else "]"

    # Trim trailing incomplete content and add closers
    # Find last complete key:value or element
    last_comma = text.rstrip().rfind(",")
    last_bracket = max(text.rstrip().rfind("}"), text.rstrip().rfind("]"))
    cut_point = max(last_comma, last_bracket) + 1
    if cut_point > len(text) - 100:  # Only fix if near the end
        return text[:cut_point] + closing
    return None


# ─── Hierarchical Chunking ──────────────────────────────────────


def chunk_text(
    text: str, max_chars: int = MAX_CHUNK_CHARS, overlap: int = CHUNK_OVERLAP
) -> list[str]:
    """Split text into sliding windows at natural sentence boundaries.

    Args:
        text: Raw text to split.
        max_chars: Maximum characters per chunk.
        overlap: Overlap between consecutive chunks.

    Returns:
        List of text chunks.
    """
    paragraphs = text.split("\n")
    chunks = []
    current = ""

    for p in paragraphs:
        if len(current) + len(p) <= max_chars:
            current += p + " "
        else:
            if current.strip():
                chunks.append(current.strip())
            # Keep tail for overlap context
            if len(current) > overlap:
                current = current[-overlap:] + p + " "
            else:
                current = p + " "

    if current.strip():
        chunks.append(current.strip())

    # If no chunks created (single paragraph), force-split
    if not chunks and len(text) > max_chars:
        for i in range(0, len(text), max_chars - overlap):
            chunks.append(text[i : i + max_chars])

    return chunks


@timing(name="structurize_hierarchical")
def structurize_hierarchical(text: str) -> dict:
    """Extract graph data from long text by chunking and merging.

    For texts > MAX_CHUNK_CHARS, processes in sliding windows,
    passing entity names forward to prevent duplicates.

    Returns merged dict compatible with StoryGraphBuilder.
    """
    if len(text) <= MAX_CHUNK_CHARS:
        return structurize_text(text)

    chunks = chunk_text(text)
    logger.info(
        "Chunked text into %d parts (%d chars → %d chunks)", len(text), len(chunks), len(chunks)
    )

    accumulated_entities: set[str] = set()
    master = {
        "entities": [],
        "events": [],
        "phases": [],
        "relationships": [],
        "causal_links": [],
        "symbols": [],
    }

    for idx, chunk in enumerate(chunks):
        # Pass known entity names to prevent duplication
        context = ""

        if accumulated_entities:
            context = f"Known existing entities in this story (do NOT recreate these): {list(accumulated_entities)[:30]}"

        if context:
            # Inject context into the system prompt by appending to user message
            chunk_data = _extract_with_context(chunk, context)
        else:
            chunk_data = structurize_text(chunk)

        # Deduplicate entities
        for e in chunk_data.get("entities", []):
            name = e.get("name", "")
            if name and name not in accumulated_entities:
                accumulated_entities.add(name)
                master["entities"].append(e)

        # Merge everything else (may create duplicates, that's OK)
        master["events"].extend(chunk_data.get("events", []))
        master["relationships"].extend(chunk_data.get("relationships", []))
        master["causal_links"].extend(chunk_data.get("causal_links", []))
        master["symbols"].extend(chunk_data.get("symbols", []))

        # Deduplicate phases by label
        existing_phase_labels = {p["label"] for p in master["phases"]}
        for ph in chunk_data.get("phases", []):
            if ph["label"] not in existing_phase_labels:
                existing_phase_labels.add(ph["label"])
                master["phases"].append(ph)

        logger.debug(
            "Chunk %d: +%d entities, total=%d",
            idx,
            len(chunk_data.get("entities", [])),
            len(master["entities"]),
        )

    return master


def _extract_with_context(text: str, context: str) -> dict:
    """Extract from text with entity context to prevent duplicates."""
    if not QWEN_API_KEY or QWEN_API_KEY == "your_qwen_api_key_here":
        return structurize_text(text)

    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
    prompt = f"""{EXTRACTION_SYSTEM}

IMPORTANT CONTEXT: {context}

Text to extract:
{text}"""

    resp = client.chat.completions.create(
        model=QWEN_LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=4000,
    )

    raw = resp.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n", "", raw)
        raw = re.sub(r"\n```$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "entities": [],
            "events": [],
            "phases": [],
            "relationships": [],
            "causal_links": [],
            "symbols": [],
        }


def build_graph(data: dict):
    """Build a StoryGraphBuilder from structured data."""
    from memory.story_graph import StoryGraphBuilder

    title = data.get("title", "untitled")
    builder = StoryGraphBuilder(title)

    # Entities
    for e in data.get("entities", []):
        builder.add_entity(e["name"], e["type"], e.get("description", ""))

    # Events
    for ev in data.get("events", []):
        builder.add_event(ev["label"], ev["description"], ev["order"], ev.get("time_period", ""))

    # Phases
    for ph in data.get("phases", []):
        builder.add_phase(ph["label"], ph.get("description", ""), ph["order"])
        for event_label in ph.get("events", []):
            builder.in_phase(event_label, ph["label"])

    # Event participants
    for ev in data.get("events", []):
        for p in ev.get("participants", []):
            builder.participate(p["entity"], ev["label"], p["role"])

    # Relationships
    for r in data.get("relationships", []):
        builder.relate(r["from"], r["to"], r["type"], r.get("context", ""))

    # Causal links
    for cl in data.get("causal_links", []):
        builder.causes(cl["from"], cl["to"], cl.get("context", ""))

    # Symbols
    for s in data.get("symbols", []):
        builder.symbol(s["entity"], s["concept"], s.get("context", ""))

    return builder


@timing(name="regenerate")
def regenerate_narrative(data: dict, lang: str = "Chinese") -> str:
    """Regenerate narrative text from structured graph data using LLM."""
    if not QWEN_API_KEY or QWEN_API_KEY == "your_qwen_api_key_here":
        raise RuntimeError("No Qwen API key configured")

    client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)

    # Compact the data into a prompt
    entities_str = "\n".join(
        f"- {e['name']} ({e['type']}): {e.get('description', '')}" for e in data.get("entities", [])
    )

    events_str = "\n".join(
        f"[{ev.get('time_period', '?')}] {ev['label']}: {ev['description']} "
        f"(participants: {', '.join(p['entity'] for p in ev.get('participants', []))})"
        for ev in data.get("events", [])
    )

    phases_str = "\n".join(
        f"## {ph['label']}: {ph.get('description', '')}" for ph in data.get("phases", [])
    )

    traits_str = "\n".join(
        f"- {r['from']} → {r['type']} → {r['to']}: {r.get('context', '')}"
        for r in data.get("relationships", [])
        if r.get("type") == "has_trait"
    )

    causal_str = "\n".join(
        f"- {cl['from']} → {cl['to']}: {cl.get('context', '')}"
        for cl in data.get("causal_links", [])
    )

    symbols_str = "\n".join(
        f"- {s['entity']} → {s['concept']}: {s.get('context', '')}" for s in data.get("symbols", [])
    )

    prompt = f"""## Life Phases
{phases_str}

## Character Traits
{traits_str}

## Events in Order
{events_str}

## Cause and Effect
{causal_str}

## Symbolic Meanings
{symbols_str}

## All Entities
{entities_str}"""

    system = REGENERATION_SYSTEM.format(lang)

    resp = client.chat.completions.create(
        model=QWEN_LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_tokens=1500,
    )

    return resp.choices[0].message.content.strip()
