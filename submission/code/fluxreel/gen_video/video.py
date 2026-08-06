#!/usr/bin/env python3
"""ww gen-video — Generate a 15s vertical short-form video (9:16) from a markdown note.

5 slides × 3 seconds each. Each slide: image centered in frame, title text at top,
subtitle text at bottom. No audio. Optimized for Douyin / WeChat Video Account.
"""

import json
import os
import re
import sys
import tempfile
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests


# ── helpers ────────────────────────────────────────────────────────────────


def _openrouter_chat(messages, model=None, max_tokens=4096, api_key=None):
    """Call OpenRouter chat completions and return the response text.

    Args:
        messages: Chat messages.
        model: Model name (default: $MODEL env var).
        max_tokens: Max tokens in response.
        api_key: OpenRouter API key. Falls back to OPENROUTER_API_KEY env var.
    """
    if not api_key:
        api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise Exception("OPENROUTER_API_KEY not provided. Set it in the frontend or in the OPENROUTER_API_KEY env var.")

    if model is None:
        model = os.getenv("MODEL")
    if not model:
        raise Exception("MODEL not specified and MODEL env var is not set. Pass --model or set MODEL=...")

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data = {"model": model, "messages": messages, "max_tokens": max_tokens}

    resp = requests.post(url, headers=headers, json=data, timeout=(10, 120))
    if not resp.ok:
        raise Exception(
            f"OpenRouter API error: HTTP {resp.status_code}\n{resp.text[:1000]}"
        )

    body = resp.json()
    msg = body.get("choices", [{}])[0].get("message", {})
    content = msg.get("content") or msg.get("reasoning") or ""
    if not content:
        raise Exception(f"Empty response from model {model}")
    return content.strip()


def _openrouter_image(prompt, image_model=None, retry_count=0):
    """Generate an image via OpenRouter's chat completions with an image model.

    Args:
        prompt: Image generation prompt.
        image_model: Model name for OpenRouter.
        retry_count: Internal — number of retries already attempted.

    Returns:
        list of image URLs (usually 1), or empty list on failure.
    """
    MAX_RETRIES = 3
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("Error: OPENROUTER_API_KEY not set.")
        sys.exit(1)

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    messages = [{"role": "user", "content": prompt}]
    data = {"model": image_model, "messages": messages, "max_tokens": 1024}

    print(f"  Generating image via {image_model}...")
    resp = requests.post(url, headers=headers, json=data, timeout=(10, 120))
    if not resp.ok:
        detail = resp.text[:500]
        if "Request Moderated" in detail or "Protected Content" in detail:
            if retry_count >= MAX_RETRIES:
                print(f"  Moderation blocked after {MAX_RETRIES} retries — giving up.")
                return []
            sanitized = _sanitize_prompt(prompt)
            print("  Moderation blocked — retrying with sanitized prompt...")
            return _openrouter_image(
                sanitized, image_model=image_model, retry_count=retry_count + 1
            )
        print(f"  Warning: Image generation failed: HTTP {resp.status_code}")
        print(f"  {detail}")
        return []

    body = resp.json()
    content = body.get("choices", [{}])[0].get("message", {}).get("content")

    if content is None:
        # Flux models return images in message.images array
        for choice in body.get("choices", []):
            msg = choice.get("message", {})
            images = msg.get("images", [])
            if images:
                urls = []
                for img in images:
                    if isinstance(img, dict):
                        img_url = img.get("image_url", {}).get("url", "") or img.get(
                            "url", ""
                        )
                        if img_url:
                            urls.append(img_url)
                if urls:
                    print(f"  Found {len(urls)} image(s) via message.images")
                    return urls
            # Check for image_url in content parts
            c = msg.get("content")
            if isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        img_url = part.get("image_url", {}).get("url", "")
                        if img_url:
                            print("  Found image URL in content parts")
                            return [img_url]
            if msg.get("url"):
                print("  Found image URL in message.url")
                return [msg["url"]]

        # Try the images endpoint format
        images = body.get("data", [])
        if images:
            urls = []
            for img in images:
                if isinstance(img, dict) and img.get("url"):
                    urls.append(img["url"])
            if urls:
                print(f"  Found {len(urls)} image(s) via data array")
                return urls

        if body.get("url"):
            print("  Found image URL in response.url")
            return [body["url"]]

        print(f"  Warning: Unexpected response format. Keys: {list(body.keys())}")
        print(f"  Response preview: {str(body)[:500]}")
        return []

    # Extract image URLs from markdown image syntax
    urls = re.findall(r"!\[.*?\]\((https?://[^\s)]+)\)", content)
    if not urls:
        urls = re.findall(
            r"https?://[^\s)]+\.(?:png|jpg|jpeg|webp)(?:\?[^\s)]*)?",
            content,
            re.IGNORECASE,
        )
    if not urls:
        print(
            f"  Warning: No image URLs found in response. Content preview: {content[:200]}"
        )
        return []

    print(f"  Got {len(urls)} image(s): {urls[0][:80]}")
    return urls


def _sanitize_prompt(prompt):
    """Remove trademarked brand names that might trigger moderation."""
    replacements = {
        r"\bNVIDIA\b": "GPU chip",
        r"\bTesla\b": "Data Center GPU",
        r"\bRTX\b": "GPU",
        r"\bGeForce\b": "Graphics Card",
        r"\bIntel\b": "Processor",
        r"\bAMD\b": "Chip maker",
    }
    result = prompt
    for pattern, replacement in replacements.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


def _download_image(url_or_data, output_path):
    """Download an image from URL or decode a base64 data URL to a local file."""
    if url_or_data.startswith("data:"):
        try:
            import base64

            match = re.match(
                r"data:image/(?:png|jpeg|jpg|webp);base64,(.+)", url_or_data
            )
            if match:
                image_data = base64.b64decode(match.group(1))
                with open(output_path, "wb") as f:
                    f.write(image_data)
                print(f"  Decoded base64 image: {output_path}")
                return True
            else:
                print("  Warning: Unknown data URL format")
                return False
        except Exception as e:
            print(f"  Warning: Failed to decode base64 image: {e}")
            return False

    try:
        resp = requests.get(url_or_data, timeout=30)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(resp.content)
        print(f"  Downloaded: {output_path}")
        return True
    except Exception as e:
        print(f"  Warning: Failed to download image: {e}")
        return False


def _strip_frontmatter(text):
    """Remove YAML frontmatter (--- ... ---) from markdown."""
    return re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)


def _generate_scenes(markdown_text, model=None, api_key=None, language=None):
    """Use LLM to generate 5 scenes with image prompts, titles, and subtitles.

    Args:
        language: 'en', 'zh', or None/'auto' (follow the article's language).
    """
    lang = (language or "auto").strip().lower()
    if lang in ("zh", "chinese", "中文", "cn", "zh-cn"):
        lang_name = "Simplified Chinese (中文)"
        title_rule = (
            "title — 2-8 个汉字（显示在幻灯片顶部，醒目、有冲击力，屏幕大字）"
        )
        subtitle_rule = (
            "subtitle — 10-25 个汉字（显示在幻灯片底部，解释性、信息性）"
        )
    elif lang in ("en", "english", "en-us"):
        lang_name = "English"
        title_rule = (
            "title — short text (2-6 words) shown at the TOP of the slide. "
            "Bold, eye-catching."
        )
        subtitle_rule = (
            "subtitle — short text (5-15 words) shown at the BOTTOM of the "
            "slide. Explanatory, informative."
        )
    else:
        lang_name = (
            "the SAME language as the article (if the article is in Chinese, "
            "write Chinese; if in English, write English)"
        )
        title_rule = (
            "title — SHORT text (2-6 words, or 2-8 characters for Chinese), "
            "shown at the TOP of the slide. Bold, eye-catching."
        )
        subtitle_rule = (
            "subtitle — SHORT text (5-15 words, or 10-25 characters for "
            "Chinese), shown at the BOTTOM of the slide. Explanatory, "
            "informative."
        )

    sys_prompt = f"""You are a video script writer for short-form tech videos (Douyin/WeChat Video Account style).

Given a markdown article, produce exactly **5 scenes**. Each scene is a 3-second slide.

Each scene needs:
1. **image_prompt** — a detailed prompt for black-forest-labs/flux.2-pro to generate a vertical image. Style: clean tech illustration, infographic style, dark background with neon accents. MUST NOT contain trademarked brand names (NVIDIA, Intel, AMD, Tesla, etc.) — use descriptive alternatives like "GPU chip", "processor company", "graphics card". Write the image_prompt in ENGLISH for best model quality.
2. **{title_rule}**
3. **{subtitle_rule}**

IMPORTANT: All **title** and **subtitle** text MUST be written in {lang_name}.

Output format — return ONLY valid JSON, no markdown fences:

{{
  "scenes": [
    {{
      "title": "Short Title",
      "subtitle": "Short explanatory subtitle for this slide.",
      "image_prompt": "Detailed image prompt for Flux."
    }}
  ]
}}"""

    messages = [
        {"role": "system", "content": sys_prompt},
        {
            "role": "user",
            "content": f"Create a 5-scene video script from this article:\n\n{markdown_text[:6000]}",
        },
    ]

    print("  Generating scenes (titles, subtitles, image prompts)...")
    raw = _openrouter_chat(messages, model=model, max_tokens=4096, api_key=api_key)

    # Strip any markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())

    # Find the outermost JSON object by tracking brace depth
    start = raw.find("{")
    if start == -1:
        print("Error: No JSON object found in LLM response.")
        print(f"Raw response:\n{raw[:500]}")
        sys.exit(1)

    depth = 0
    end = start
    in_string = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if not in_string:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
    if depth != 0:
        print("Error: Unmatched braces in LLM response.")
        print(f"Raw response:\n{raw[:500]}")
        sys.exit(1)

    json_str = raw[start : end + 1]
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"Error: Could not parse LLM response as JSON: {e}")
        print(f"Raw response:\n{raw[:500]}")
        sys.exit(1)

    scenes = data.get("scenes", [])
    if not scenes:
        print("Error: LLM response missing scenes.")
        print(f"Parsed JSON: {json.dumps(data, indent=2)[:500]}")
        sys.exit(1)

    print(f"  {len(scenes)} scenes generated")
    return scenes


def _generate_scene_image(scene_index, prompt, temp_dir, image_model):
    """Generate an image for a single scene using OpenRouter and download it.

    Thread-safe — all state is local or passed in.

    Returns:
        (index: int, path: str) — the scene index and path to the downloaded image.
    """
    img_urls = _openrouter_image(prompt, image_model=image_model)
    if img_urls:
        img_path = temp_dir / f"raw_scene_{scene_index:03d}.png"
        if _download_image(img_urls[0], str(img_path)):
            return (scene_index, str(img_path))
    # Fall through: create placeholder
    placeholder = temp_dir / f"raw_scene_{scene_index:03d}.png"
    from PIL import Image as PILImage

    bg = PILImage.new("RGB", (1080, 1920), (20, 20, 40))
    bg.save(str(placeholder))
    return (scene_index, str(placeholder))


def _generate_scene_image_with_provider(scene_index, prompt, temp_dir, provider):
    """Generate an image for a single scene using the given provider.

    Args:
        scene_index: Scene index.
        prompt: Image generation prompt.
        temp_dir: Temporary directory to save the image.
        provider: An ImageProvider instance.

    Returns:
        (index: int, path: str) — the scene index and path to the downloaded image.
    """
    img_path = provider.generate_image(prompt, scene_index=scene_index)
    if img_path and os.path.isfile(img_path):
        # Move to temp_dir for consistent cleanup
        dest = temp_dir / f"raw_scene_{scene_index:03d}.png"
        import shutil
        shutil.copy2(img_path, dest)
        return (scene_index, str(dest))
    # Fall through: create placeholder
    placeholder = temp_dir / f"raw_scene_{scene_index:03d}.png"
    from PIL import Image as PILImage
    bg = PILImage.new("RGB", (1080, 1920), (20, 20, 40))
    bg.save(str(placeholder))
    return (scene_index, str(placeholder))


def _create_slide_frame(
    image_path, title, subtitle, output_path, width=1080, height=1920
):
    """Create a full slide frame: 4:3 image centered + top title + bottom subtitle.

    The image is 1080x810 (4:3) and centered vertically in the frame, so the
    title and subtitle sit symmetrically around it. Source images are
    cover-cropped to fill the 4:3 area exactly (no distortion).
    """
    from PIL import Image, ImageDraw, ImageFont

    # Create black background
    frame = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(frame)

    # Load the scene image
    if os.path.isfile(image_path):
        try:
            scene_img = Image.open(image_path).convert("RGB")
        except Exception:
            scene_img = None
    else:
        scene_img = None

    # 4:3 image area (1080x810), centered vertically so text sits around it
    img_area_width = width
    img_area_height = int(width * 3 / 4)  # 810
    img_area_top = (height - img_area_height) // 2  # 555
    img_area_bottom = img_area_top + img_area_height  # 1365

    if scene_img:
        # Cover-crop the source to fill exactly 4:3 (center crop, no distortion)
        target_aspect = img_area_width / img_area_height  # 4:3 = 1.333
        src_aspect = scene_img.width / scene_img.height
        if src_aspect > target_aspect:
            # Source is wider — crop the sides
            new_w = int(scene_img.height * target_aspect)
            new_h = scene_img.height
        else:
            # Source is taller — crop the top/bottom
            new_w = scene_img.width
            new_h = int(scene_img.width / target_aspect)
        left = (scene_img.width - new_w) // 2
        top = (scene_img.height - new_h) // 2
        scene_img = scene_img.crop((left, top, left + new_w, top + new_h))
        scene_img = scene_img.resize(
            (img_area_width, img_area_height), Image.LANCZOS
        )
        frame.paste(scene_img, (0, img_area_top))

    # Load fonts (macOS + Linux paths; bold face for the title).
    # When the text contains CJK characters, use a CJK-capable font
    # (DejaVu/Liberation do not cover Chinese/Japanese glyphs).
    def _has_cjk(text):
        return any(
            "\u4e00" <= ch <= "\u9fff"  # CJK Unified Ideographs
            or "\u3000" <= ch <= "\u303f"  # CJK punctuation
            or "\uff00" <= ch <= "\uffef"  # fullwidth forms
            for ch in (text or "")
        )

    needs_cjk = _has_cjk(title) or _has_cjk(subtitle)

    def _load_font(size, candidates, cjk=False):
        """Try each (path, face-index) pair; return PIL font or default.

        When cjk=True and every explicit path fails, ask fontconfig for any
        installed CJK-capable font (fc-match) as a last resort so Chinese
        text never falls back to the non-CJK default bitmap font (tofu).
        """
        for fp, index in candidates:
            if os.path.exists(fp):
                try:
                    return ImageFont.truetype(fp, size, index=index)
                except Exception:
                    continue
        if cjk:
            try:
                import subprocess
                out = subprocess.run(
                    ["fc-match", "-f", "%{file}:%{index}", ":lang=zh-cn"],
                    capture_output=True, text=True, timeout=5,
                ).stdout.strip()
                if out and ":" in out:
                    fp, _, idx = out.rpartition(":")
                    if os.path.exists(fp):
                        return ImageFont.truetype(fp, size, index=int(idx))
            except Exception:
                pass
        return ImageFont.load_default()

    if needs_cjk:
        TITLE_SIZE = 100  # CJK glyphs are denser; slightly smaller reads better
        SUBTITLE_SIZE = 64
        title_candidates = [
            ("/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc", 2),  # SC
            ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),  # SC
            ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc", 0),
            ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
            ("/System/Library/Fonts/Helvetica.ttc", 0),
        ]
        subtitle_candidates = [
            ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),  # SC
            ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
            ("/Library/Fonts/Arial.ttf", 0),
        ]
    else:
        TITLE_SIZE = 110
        SUBTITLE_SIZE = 64
        title_candidates = [
            ("/System/Library/Fonts/Helvetica.ttc", 0),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
            ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 0),
        ]
        subtitle_candidates = [
            ("/Library/Fonts/Arial.ttf", 0),
            ("/System/Library/Fonts/Supplemental/Arial.ttf", 0),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
            ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 0),
        ]

    title_font = _load_font(TITLE_SIZE, title_candidates, cjk=needs_cjk)
    subtitle_font = _load_font(SUBTITLE_SIZE, subtitle_candidates, cjk=needs_cjk)

    def _wrap_text(text, font, max_width):
        """Wrap text to fit max_width.

        CJK text has no spaces, so it wraps per character; Latin text wraps
        per word. Any single over-long token is hard-broken by characters.
        """
        if _has_cjk(text):
            lines, cur = [], ""
            for ch in text:
                test = cur + ch
                bb = draw.textbbox((0, 0), test, font=font)
                if bb[2] - bb[0] > max_width and cur:
                    lines.append(cur)
                    cur = ch
                else:
                    cur = test
            if cur:
                lines.append(cur)
            return lines
        words = text.split()
        lines, cur = [], ""
        for w in words:
            test = f"{cur} {w}".strip()
            bb = draw.textbbox((0, 0), test, font=font)
            if bb[2] - bb[0] > max_width:
                if cur:
                    lines.append(cur)
                # Hard-break an over-long word by characters
                if _has_cjk(w):
                    cur = ""
                    for ch in w:
                        test2 = cur + ch
                        bb2 = draw.textbbox((0, 0), test2, font=font)
                        if bb2[2] - bb2[0] > max_width and cur:
                            lines.append(cur)
                            cur = ch
                        else:
                            cur = test2
                else:
                    cur = w
            else:
                cur = test
        if cur:
            lines.append(cur)
        return lines

    # ── Top title: just above the image area ──────────────────────────
    # Sits directly above the centered 4:3 image (y=382-555)
    title_bar_top = img_area_top - int(height * 0.09)
    title_bar_height = int(height * 0.09)
    draw.rectangle(
        [0, title_bar_top, width, title_bar_top + title_bar_height], fill=(0, 0, 0, 200)
    )

    # Center the title text (max 2 lines, shrink font until it fits the bar)
    title_lines = _wrap_text(title, title_font, width - 80)
    while (
        len(title_lines) > 2
        or len(title_lines) * int(title_font.size * 1.25) > title_bar_height
    ) and getattr(title_font, "size", 0) > 48:
        title_font = _load_font(title_font.size - 8, title_candidates)
        title_lines = _wrap_text(title, title_font, width - 80)
    line_height_t = int(title_font.size * 1.25)
    total_title_h = len(title_lines) * line_height_t
    title_y = title_bar_top + (title_bar_height - total_title_h) // 2
    for i, line in enumerate(title_lines):
        bb = draw.textbbox((0, 0), line, font=title_font)
        x = (width - (bb[2] - bb[0])) // 2
        draw.text((x, title_y + i * line_height_t), line, fill="white", font=title_font)

    # ── Bottom subtitle: just below the image area ────────────────────
    # Sits directly below the centered 4:3 image (y=1365-1538)
    subtitle_bar_top = img_area_bottom
    subtitle_bar_height = int(height * 0.09)
    draw.rectangle(
        [0, subtitle_bar_top, width, subtitle_bar_top + subtitle_bar_height],
        fill=(0, 0, 0, 200),
    )

    # Word-wrap subtitle (max 3 lines, shrink font until it fits the bar)
    sub_lines = _wrap_text(subtitle, subtitle_font, width - 100)
    while (
        len(sub_lines) > 3
        or len(sub_lines) * int(subtitle_font.size * 1.2) > subtitle_bar_height
    ) and getattr(subtitle_font, "size", 0) > 32:
        subtitle_font = _load_font(subtitle_font.size - 4, subtitle_candidates)
        sub_lines = _wrap_text(subtitle, subtitle_font, width - 100)

    # Center subtitle text vertically in bottom bar
    line_height = int(subtitle_font.size * 1.2)
    total_text_height = len(sub_lines) * line_height
    text_start_y = subtitle_bar_top + (subtitle_bar_height - total_text_height) // 2

    for i, line in enumerate(sub_lines):
        bbox = draw.textbbox((0, 0), line, font=subtitle_font)
        line_w = bbox[2] - bbox[0]
        x = (width - line_w) // 2
        y = text_start_y + i * line_height
        draw.text((x, y), line, fill="white", font=subtitle_font)

    # Add a subtle gradient line separator between bars and image area
    for y_offset in range(3):
        draw.rectangle(
            [
                0,
                title_bar_top + title_bar_height + y_offset,
                width,
                title_bar_top + title_bar_height + y_offset + 1,
            ],
            fill=(50, 50, 50, 100),
        )
        draw.rectangle(
            [0, subtitle_bar_top + y_offset, width, subtitle_bar_top + y_offset + 1],
            fill=(50, 50, 50, 100),
        )

    frame.save(output_path, "PNG")
    return output_path


def generate_video_from_content(
    md_content,
    output_path,
    model=None,
    image_model="black-forest-labs/flux.2-pro",
    verbose=True,
    provider=None,
    local_variant="schnell",
    api_key=None,
    language=None,
):
    """Run the full video generation pipeline from markdown content.

    Steps: generate scenes → generate images → create slide frames → assemble video.

    Args:
        md_content: Markdown text (already stripped of frontmatter).
        output_path: Where to write the final .mp4.
        model: LLM model for script generation (default: $MODEL env var).
        image_model: Image generation model (for OpenRouter provider).
        verbose: If True, print progress to stdout.
        provider: 'openrouter', 'local', or 'auto'. If None, uses OpenRouter.
        local_variant: Which local FLUX variant ('schnell', 'dev', '2-dev').
        api_key: OpenRouter API key (overrides env var).
        language: 'en', 'zh', or None/'auto' (follow article language).

    Returns:
        (success: bool, output_path: str or None, error_msg: str or None)
    """
    _p = print if verbose else lambda *a, **kw: None

    # Use default LLM model if none specified
    if model is None:
        model = os.getenv("MODEL") or "openrouter/auto-beta"
    _p(f"Using LLM model: {model}")

    _p("Step 1/3: Generating scenes (titles, subtitles, image prompts)...")
    scenes = _generate_scenes(md_content, model=model, api_key=api_key, language=language)
    _p(f"Scenes: {len(scenes)}")

    for i, s in enumerate(scenes):
        _p(f'  Scene {i + 1}: "{s.get("title", "")}" — {s.get("subtitle", "")[:60]}...')

    # ── Step 2: Generate images via selected provider ──────────────────────
    from fluxreel.gen_video.providers.factory import create_provider

    image_provider = None
    if provider and provider != "openrouter":
        try:
            image_provider = create_provider(
                provider=provider,
                model=image_model,
                local_variant=local_variant,
                api_key=api_key,
            )
            _p(f"Using image provider: {image_provider.name} ({image_provider.model_name})")
        except Exception as e:
            _p(f"Warning: Could not create provider '{provider}': {e}")
            _p("  Falling back to OpenRouter")
            image_provider = None

    _p(f"\nStep 2/3: Generating images...")
    temp_dir = Path(tempfile.mkdtemp(prefix="gen_video_"))
    raw_image_paths = []

    # Pre-import torch/diffusers for local GPU to avoid race conditions
    if image_provider is not None and hasattr(image_provider, '_load_model'):
        _p("  Pre-loading model (single thread)...")
        try:
            image_provider._load_model()
        except Exception as e:
            _p(f"  Pre-load failed: {e}")

    # Submit all scenes in parallel
    results: dict[int, str] = {}
    scene_indices = [i for i, s in enumerate(scenes) if s.get("image_prompt")]
    worker_count = max(1, len(scene_indices))

    with ThreadPoolExecutor(max_workers=worker_count) as ex:
        futures = {}
        for i in scene_indices:
            prompt = scenes[i].get("image_prompt", "")
            _p(f"  Submitting scene {i + 1}/{len(scenes)}: {prompt[:80]}...")
            if image_provider:
                futures[
                    ex.submit(_generate_scene_image_with_provider, i, prompt, temp_dir, image_provider)
                ] = i
            else:
                futures[
                    ex.submit(_generate_scene_image, i, prompt, temp_dir, image_model or "black-forest-labs/flux.2-pro")
                ] = i

        for future in as_completed(futures):
            i = futures[future]
            try:
                idx, path = future.result()
                results[idx] = path
                _p(f"  Scene {i + 1} done")
            except Exception as e:
                _p(f"  Scene {i + 1} exception: {e}")
                placeholder = temp_dir / f"raw_scene_{i:03d}.png"
                from PIL import Image as PILImage

                bg = PILImage.new("RGB", (1080, 1920), (20, 20, 40))
                bg.save(str(placeholder))
                results[i] = str(placeholder)

    # Collect results in scene order
    for i in range(len(scenes)):
        if i in results:
            raw_image_paths.append(results[i])

    # Ensure exactly 5 images (pad or trim)
    while len(raw_image_paths) < 5:
        placeholder = temp_dir / f"raw_scene_{len(raw_image_paths):03d}.png"
        from PIL import Image as PILImage

        bg = PILImage.new("RGB", (1080, 1920), (20, 20, 40))
        bg.save(str(placeholder))
        raw_image_paths.append(str(placeholder))
    raw_image_paths = raw_image_paths[:5]

    # ── Step 3: Create slide frames with text overlays ────────────────────
    _p("\nStep 3/3: Creating slide frames and assembling video...")
    slide_frames = []
    for i, (img_path, scene) in enumerate(zip(raw_image_paths, scenes[:5])):
        title = scene.get("title", "")
        subtitle = scene.get("subtitle", "")
        slide_path = temp_dir / f"slide_{i:03d}.png"
        _create_slide_frame(img_path, title, subtitle, str(slide_path))
        slide_frames.append(str(slide_path))
        _p(f'  Slide {i + 1}: "{title}"')

    # ── Step 4: Assemble video with background music ─────────────────────
    _p("\nAssembling video (5 slides × 3s = 15s)...")
    try:
        seg_files = []
        for i, slide_path in enumerate(slide_frames):
            seg_file = temp_dir / f"seg_{i:03d}.mp4"
            _p(f"  Encoding segment {i + 1}/5...")
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loop",
                    "1",
                    "-i",
                    str(slide_path),
                    "-c:v",
                    "libx264",
                    "-t",
                    "3",
                    "-pix_fmt",
                    "yuv420p",
                    "-r",
                    "30",
                    "-vf",
                    "scale=1080:1920",
                    str(seg_file),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            seg_files.append(str(seg_file))

        concat_file = temp_dir / "concat.txt"
        with open(concat_file, "w") as f:
            for s in seg_files:
                f.write(f"file '{s}'\n")

        concat_video = temp_dir / "concat_video.mp4"
        _p("  Concatenating segments...")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(concat_video),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )

        # Add background music: trim to 15s, fade out last 1s, lower volume
        bg_music = os.path.join(os.path.dirname(__file__), "bg.mp3")
        if os.path.isfile(bg_music):
            _p("  Adding background music with fade-out...")
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(concat_video),
                    "-i",
                    bg_music,
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "128k",
                    "-filter_complex",
                    "[1:a]atrim=0:15,afade=t=out:st=14:d=1,volume=0.3[a]",
                    "-map",
                    "0:v",
                    "-map",
                    "[a]",
                    "-shortest",
                    output_path,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        else:
            _p(f"  Skipping audio (bg.mp3 not found at {bg_music})")
            subprocess.run(
                ["cp", str(concat_video), output_path],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )

        success = True
        error_msg = None
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr[:500] if e.stderr else str(e)
        _p(f"Error: FFmpeg failed: {error_msg}")
        success = False
    except Exception as e:
        error_msg = str(e)
        _p(f"Error: {error_msg}")
        success = False

    # Cleanup
    _p("  Cleaning up temp files...")
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)

    if success:
        _p(f"\n✓ Video created: {output_path}")
        try:
            size = os.path.getsize(output_path)
            _p(f"  Size: {size / 1024 / 1024:.1f} MB")
            dur = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    output_path,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            d = json.loads(dur.stdout)["format"]["duration"]
            _p(f"  Duration: {float(d):.1f}s")
        except Exception:
            pass

    return (success, output_path if success else None, error_msg)


def main():
    try:
        from fluxreel.env import load_env as _le

        _le()
    except ImportError:
        pass

    # Parse args
    args = list(sys.argv[1:])

    if not args or "--help" in args or "-h" in args:
        print("Usage: ww gen-video <file_path> [options]")
        print()
        print(
            "Generate a 15-second vertical short-form video (9:16) from a markdown note."
        )
        print("5 slides × 3 seconds each. No audio.")
        print("Optimized for Douyin / WeChat Video Account.")
        print()
        print("Options:")
        print(
            "  --output PATH       Output video path (default: <input_name>_video.mp4)"
        )
        print("  --model MODEL       LLM model for script generation (default: $MODEL)")
        print(
            "  --image-model MODEL Image generation model (default: black-forest-labs/flux.2-pro)"
        )
        print("  --provider PROVIDER Image provider: openrouter, local, auto (default: openrouter)")
        print("  --local-variant VAR Local FLUX variant: schnell, dev, 2-dev (default: schnell)")
        print("  --upload            Upload generated video to YouTube after creation")
        print(
            "  --private           When uploading, set video to private (default: public)"
        )
        print()
        print("Subcommands:")
        print("  server              Start the gen-video API server")
        print()
        print("Examples:")
        print("  ww gen-video notes/2026-07-20-tesla-p100-vs-m60-for-ai-en.md")
        print("  ww gen-video notes/2026-07-20-tesla-p100-vs-m60-for-ai-en.md --upload")
        return

    file_path = args[0]

    output_path = None
    model = None
    image_model = "black-forest-labs/flux.2-pro"
    provider = None
    local_variant = "schnell"
    do_upload = False
    upload_private = False

    i = 1
    while i < len(args):
        if args[i] == "--output" and i + 1 < len(args):
            output_path = args[i + 1]
            i += 2
        elif args[i] == "--model" and i + 1 < len(args):
            model = args[i + 1]
            i += 2
        elif args[i] == "--image-model" and i + 1 < len(args):
            image_model = args[i + 1]
            i += 2
        elif args[i] == "--provider" and i + 1 < len(args):
            provider = args[i + 1]
            i += 2
        elif args[i] == "--local-variant" and i + 1 < len(args):
            local_variant = args[i + 1]
            i += 2
        elif args[i] == "--upload":
            do_upload = True
            i += 1
        elif args[i] == "--private":
            upload_private = True
            i += 1
        else:
            print(f"Unknown option: {args[i]}")
            sys.exit(1)

    # Resolve input file
    file_path = os.path.expanduser(file_path)
    if not os.path.isfile(file_path):
        print(f"Error: File not found: {file_path}")
        sys.exit(1)

    if output_path is None:
        base = os.path.splitext(os.path.basename(file_path))[0]
        output_path = f"{base}_video.mp4"

    # ── Step 1: Read markdown ──────────────────────────────────────────────
    print(f"Reading: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        raw_md = f.read()
    md_content = _strip_frontmatter(raw_md)
    print(f"Content length: {len(md_content)} chars")

    # ── Run pipeline ───────────────────────────────────────────────────────
    success, out_path, error_msg = generate_video_from_content(
        md_content, output_path, model=model, image_model=image_model, verbose=True,
        provider=provider, local_variant=local_variant,
    )

    if not success:
        print("\n✗ Video creation failed.")
        if error_msg:
            print(f"  {error_msg}")
        sys.exit(1)

    # ── Upload to YouTube if requested ──────────────────────────────────
    if do_upload:
        print("\n── Uploading to YouTube ──")
        saved_argv = list(sys.argv)
        upload_args = [saved_argv[0], file_path, output_path]
        if upload_private:
            upload_args.append("--private")
        sys.argv = upload_args
        try:
            from fluxreel.gen_video.youtube_upload import main as upload_main

            upload_main()
        except Exception as e:
            print(f"Upload failed: {e}")
        finally:
            sys.argv = saved_argv
