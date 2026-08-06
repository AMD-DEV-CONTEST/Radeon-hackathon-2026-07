# Judge Demo Walkthrough

> Follow this script to cover everything in 5 minutes — calm and complete.

## Pre-Demo Preparation (do in advance)

1. Confirm the `radeon` provider's API Key is valid (check at the [Token Factory](https://developer.amd.com.cn/radeon/modelapis)).
2. If ComfyUI is running on a Radeon instance, confirm the SSH tunnel is connected.
3. Confirm the WeChat Official Account AppID/AppSecret are filled in (needed for draft-box publishing).
4. **Pre-generate 1–2 articles and save them** (if the venue network is slow, show the finished articles from History instead).

## Demo Flow (5 minutes)

### Step 1: Product Introduction (30 seconds)

Open the app → the intro page (`/demo`) shows automatically:
- Read the tagline: "Photos + theme → one-click WeChat article + Xiaohongshu note → straight to the draft box, all on AMD GPU."
- Point out the four track scoring pillars (inference acceleration / lightweight deployment / style customization / image quality optimization).
- If ComfyUI is connected, point to the "GPU Status" area (shows the AMD GPU model + VRAM).

### Step 2: Generate an Article (2 minutes)

Click "Try It Now" → enter the home page:
1. Enter a theme (e.g. "Radeon GPU performance hands-on").
2. Upload 2–3 screenshots.
3. Pick a style for each photo (e.g. anime), or choose "None".
4. Pick a template (e.g. "Product Review").
5. Click "Generate".

> Watch the progress bar: "Writing article 10% (waiting 45s)" — the ticking seconds mean it is running.
>
> **If it is too slow**: open History and show a pre-generated article (say "this was generated earlier on an AMD GPU").

### Step 3: Show the Result (1.5 minutes)

Once the preview page opens:
1. **Cover**: the AI-generated 2.35:1 card cover at the top (if ComfyUI is available).
2. **Title + summary**.
3. **Body**: text interleaved with images — point out "this 3DMark screenshot was automatically placed next to the paragraph about 3DMark — the vision model read the text in the image."
4. **Captions**: each image has an AI-written caption.
5. **Timing**: "text took Xs, images took Ys."
6. **Editable**: click in, change a few words, drag an image — "everything is editable after generation."

### Step 4: Publish to Draft Box (30 seconds)

Click "Send to WeChat Draft Box":
- A `media_id` popup = success.
- "This article is now in my WeChat Official Account draft box — I can log into the backend to view, edit, and publish it."

### Step 5: Wrap-Up (30 seconds)

- Click "Regenerate" to show "if you're not satisfied, run it again."
- Open the History page to show "all previously generated articles are stored."
- One-sentence summary: "Content Studio chains AI writing, AMD GPU image styling, vision-based image placement, and direct WeChat publishing into a complete multimodal content creation pipeline."

## Q&A Cheat Sheet

| Judges may ask | Key points of the answer |
|---|---|
| Where is the AMD GPU used? | Text: Radeon Cloud (Qwen on AMD GPU); Images: ComfyUI on ROCm (AMD GPU style transfer + text-to-image). |
| How is this different from just using ChatGPT? | ① Vision-based image placement ② Photo stylization (ComfyUI on AMD GPU) ③ Direct draft-box publishing (API) ④ Editable preview ⑤ Xiaohongshu support too ⑥ AMD GPU end to end. |
| Why Radeon Cloud? | Provided by the organizer; the free shared API works out of the box; a dedicated vLLM instance gives you an exclusive GPU for more speed. |
| How is stylization done? | ComfyUI img2img (DreamShaper 8), denoise 0.55 — keeps composition, changes style. 8 presets + custom workflows. |
| How would others deploy it? | FastAPI server / PyWebView desktop app / see the ROCm Migration Guide for details. |
