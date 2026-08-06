import os

import gradio as gr
from PIL import Image
from auth_vscode import (
    authenticate_user,
    ensure_admin_account,
    register,
    resend_verification_otp,
    request_password_reset,
    reset_password,
    verify_email,
)
from database_vscode import (
    get_registered_users,
    get_recent_logins,
    get_user_history,
    init_db,
    save_generation,
)
from model_vscode import SCHEDULERS, SDXLGenerator

init_db()
generator = SDXLGenerator()
ADMIN_PASSWORD = os.getenv("GENAI_ADMIN_PASSWORD", "Gnk2005/09-07")
ensure_admin_account(password=ADMIN_PASSWORD)

EXAMPLE_IMAGES = [
    ("Photorealistic AI Portrait", "https://images.unsplash.com/photo-1529626455594-4ff0802cfb7e?auto=format&fit=crop&w=900&q=80"),
    ("Cyberpunk City", "https://images.unsplash.com/photo-1519608487953-e999c86e7455?auto=format&fit=crop&w=900&q=80"),
    ("Fantasy Landscape", "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=900&q=80"),
    ("Creative Studio", "https://images.unsplash.com/photo-1497366754035-f200968a6e72?auto=format&fit=crop&w=900&q=80"),
    ("Generative Interface", "https://images.unsplash.com/photo-1550745165-9bc0b252726f?auto=format&fit=crop&w=900&q=80"),
    ("Neural Network", "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?auto=format&fit=crop&w=900&q=80"),
    ("Digital Art", "https://images.unsplash.com/photo-1547891654-e66ed7ebb968?auto=format&fit=crop&w=900&q=80"),
]

APP_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Anton&family=Inter:wght@400;500;600;700;800&display=swap');

:root {
    --bg: #060712;
    --panel: #0d1020;
    --panel-2: #13172b;
    --line: rgba(255,255,255,.12);
    --text: #f8fafc;
    --muted: #9aa0c4;
    --cyan: #0ee7ff;
    --violet: #7c3aed;
}

.gradio-container {
    max-width: 100% !important;
    padding: 0 !important;
    background: radial-gradient(circle at 70% 40%, rgba(124,58,237,.18), transparent 35%),
                radial-gradient(circle at 18% 38%, rgba(14,231,255,.13), transparent 28%),
                linear-gradient(120deg, #07111b 0%, #070814 42%, #0a0618 100%) !important;
    color: var(--text) !important;
    font-family: Inter, sans-serif !important;
}

body, .main, .wrap, footer { background: #060712 !important; }
footer { opacity: .35; }

.app-frame {
    min-height: 100vh;
    background-image:
      linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
    background-size: 34px 34px;
}

.topbar {
    position: sticky;
    top: 0;
    z-index: 20;
    height: 98px;
    display: flex;
    align-items: center;
    gap: 32px;
    padding: 0 60px;
    border-bottom: 1px solid rgba(255,255,255,.08);
    background: rgba(5,6,16,.86);
    backdrop-filter: blur(18px);
}

.brand {
    font-family: Anton, Impact, sans-serif;
    font-size: 34px;
    letter-spacing: 2px;
}

.brand span { color: var(--cyan); }

.nav-copy {
    display: flex;
    gap: 34px;
    color: var(--muted);
    font-weight: 800;
    font-size: 17px;
}

.nav-copy b { color: #fff; }

.hero {
    display: grid;
    grid-template-columns: minmax(360px, 620px) minmax(420px, 720px);
    align-items: center;
    gap: 70px;
    min-height: 760px;
    padding: 90px 100px 80px;
}

.pill {
    display: inline-flex;
    padding: 12px 22px;
    border-radius: 999px;
    border: 1px solid rgba(14,231,255,.32);
    background: rgba(14,231,255,.08);
    color: var(--cyan);
    font-weight: 900;
    letter-spacing: 1px;
}

.hero h1 {
    font-family: Anton, Impact, sans-serif;
    font-size: clamp(72px, 8vw, 132px);
    line-height: .96;
    letter-spacing: 0;
    margin: 28px 0 26px;
}

.hero h1 span {
    color: transparent;
    -webkit-text-stroke: 3px var(--cyan);
}

.hero p {
    max-width: 620px;
    color: var(--muted);
    font-size: 20px;
    line-height: 1.7;
}

.hero-actions {
    display: flex;
    gap: 18px;
    margin: 38px 0 26px;
}

.cta {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 66px;
    padding: 0 36px;
    border-radius: 999px;
    background: var(--cyan);
    color: #020617;
    font-weight: 900;
    font-size: 18px;
}

.ghost {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 66px;
    padding: 0 36px;
    border-radius: 999px;
    border: 1px solid rgba(255,255,255,.14);
    background: rgba(255,255,255,.06);
    color: #fff;
    font-weight: 900;
    font-size: 18px;
}

.ticks {
    display: flex;
    flex-wrap: wrap;
    gap: 24px;
    color: var(--muted);
    font-weight: 700;
}

.showcase {
    position: relative;
    min-height: 560px;
}

.showcase-card {
    position: absolute;
    width: 330px;
    height: 430px;
    border-radius: 26px;
    overflow: hidden;
    box-shadow: 0 36px 90px rgba(0,0,0,.45);
    border: 1px solid rgba(255,255,255,.12);
    background: #111827;
}

.showcase-card img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
}

.showcase-card strong {
    position: absolute;
    left: 22px;
    bottom: 24px;
    padding: 10px 12px;
    border-radius: 999px;
    background: rgba(2,6,23,.72);
    color: #fff;
    font-size: 15px;
}

.card-one { left: 40px; top: 110px; transform: rotate(-9deg); }
.card-two { left: 190px; top: 64px; transform: rotate(2deg); }
.card-three { left: 340px; top: 24px; transform: rotate(6deg); }

.section {
    max-width: 1480px;
    margin: 0 auto;
    padding: 70px 70px;
}

.section h2 {
    font-family: Anton, Impact, sans-serif;
    font-size: clamp(44px, 5vw, 76px);
    line-height: 1;
    margin: 0 0 22px;
}

.section p { color: var(--muted); font-size: 18px; line-height: 1.7; }

.example-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 22px;
    margin-top: 32px;
}

.example-card {
    position: relative;
    aspect-ratio: 1 / 1;
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid rgba(255,255,255,.1);
    background: #111827;
}

.example-card img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    filter: saturate(1.08) contrast(1.04);
}

.example-card span {
    position: absolute;
    left: 14px;
    bottom: 14px;
    right: 14px;
    padding: 10px 12px;
    border-radius: 8px;
    background: rgba(2,6,23,.76);
    color: #fff;
    font-weight: 900;
}

.feature-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 18px;
    margin-top: 28px;
}

.feature-card {
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 24px;
    background: linear-gradient(180deg, rgba(19,23,43,.92), rgba(10,12,27,.92));
    min-height: 180px;
}

.feature-card h3 { margin: 0 0 10px; font-size: 20px; }
.feature-card p { margin: 0; color: var(--muted); font-size: 16px; }

.status-pill {
    margin: 0 60px 24px;
    padding: 12px 16px;
    border-radius: 999px;
    background: rgba(14,231,255,.08);
    border: 1px solid rgba(14,231,255,.25);
    color: #bdf7ff;
    font-weight: 800;
}

.gradio-container .tabs {
    max-width: 1480px;
    margin: 0 auto !important;
    padding: 0 70px 70px !important;
}

.gr-button-primary, button.primary {
    background: var(--cyan) !important;
    border: 0 !important;
    color: #020617 !important;
    font-weight: 900 !important;
}

.gr-button-secondary, button.secondary {
    background: rgba(255,255,255,.07) !important;
    color: #fff !important;
    border: 1px solid rgba(255,255,255,.14) !important;
}

.block, .form, .panel, .tabitem {
    background: rgba(13,16,32,.82) !important;
    border-color: rgba(255,255,255,.1) !important;
}

.input-container, textarea, input, select {
    background: #0c1020 !important;
    color: var(--text) !important;
    border-color: rgba(255,255,255,.14) !important;
}

label, .label-wrap span { color: #e2e8f0 !important; font-weight: 800 !important; }

.info-table table { width: 100%; border-collapse: collapse; }
.info-table td, .info-table th {
    border-bottom: 1px solid var(--line);
    padding: 12px;
    text-align: left;
}
.info-table th { color: #cffafe; }

@media (max-width: 1050px) {
    .hero { grid-template-columns: 1fr; padding: 60px 28px; }
    .showcase { min-height: 460px; transform: scale(.82); transform-origin: left top; }
    .example-grid, .feature-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .topbar { padding: 0 24px; gap: 18px; }
    .nav-copy { display: none; }
    .gradio-container .tabs { padding: 0 24px 60px !important; }
    .status-pill { margin: 0 24px 24px; }
}

@media (max-width: 640px) {
    .example-grid, .feature-grid { grid-template-columns: 1fr; }
    .hero h1 { font-size: 68px; }
    .hero-actions { flex-direction: column; }
    .showcase { display: none; }
}
"""


def examples_html():
    cards = "\n".join(
        f"<div class='example-card'><img src='{url}' alt='{title}'><span>{title}</span></div>"
        for title, url in EXAMPLE_IMAGES
    )
    return f"""
    <div class="section">
      <h2>PROJECT CREATIONS</h2>
      <p>Example visual directions for secure text-to-image generation, AI creativity, and project presentation.</p>
      <div class="example-grid">{cards}</div>
    </div>
    """


HOME_MD = f"""
<div class="app-frame">
  <div class="topbar">
    <div class="brand">GEN<span>AI</span></div>
    <div class="nav-copy">
      <b>Generate</b>
      <span>Gallery</span>
      <span>Features</span>
      <span>About</span>
    </div>
    <div class="pill">Secure Image Studio</div>
  </div>

  <div class="hero">
    <div>
      <div class="pill">Powered by SDXL, PyTorch Diffusion, and secure OTP login</div>
      <h1>WORDS<br><span>BECOME</span><br>WORLDS.</h1>
      <p>Type a description and transform it into original AI artwork. The website includes registration, email OTP verification, forgot-password OTP, admin tracking, saved image history, and a polished gallery.</p>
      <p class="pill">Use the real tabs below: Generate Image, Gallery, Sign In / OTP, Register, and Admin.</p>
      <div class="ticks">
        <span>Text to image</span>
        <span>Email OTP security</span>
        <span>Admin login history</span>
        <span>Saved gallery</span>
      </div>
    </div>

    <div class="showcase">
      <div class="showcase-card card-one"><img src="{EXAMPLE_IMAGES[2][1]}" alt="Fantasy"><strong>Fantasy Worlds</strong></div>
      <div class="showcase-card card-two"><img src="{EXAMPLE_IMAGES[1][1]}" alt="Cyberpunk"><strong>Cyberpunk City</strong></div>
      <div class="showcase-card card-three"><img src="{EXAMPLE_IMAGES[3][1]}" alt="Creative Studio"><strong>Image Studio</strong></div>
    </div>
  </div>
</div>
"""

def load_frontend_asset(filename, fallback):
    path = os.path.join(os.path.dirname(__file__), "frontend", filename)
    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        return fallback


APP_CSS = load_frontend_asset("style.css", APP_CSS)
HOME_MD = load_frontend_asset("home.html", HOME_MD)

FEATURES_MD = """
<div class="section">
  <h2>FEATURES</h2>
  <p>This project combines SDXL text-to-image generation, secure user authentication, OTP email verification, saved history, admin monitoring, and a polished web interface.</p>
  <div class="feature-grid">
    <div class="feature-card"><h3>High-Level Text to Image</h3><p>Uses SDXL through Diffusers with prompt, negative prompt, seed, scheduler, size, steps, and guidance controls.</p></div>
    <div class="feature-card"><h3>Email OTP Verification</h3><p>Sends an OTP to the registered email address after registration before normal users can sign in.</p></div>
    <div class="feature-card"><h3>Forgot Password OTP</h3><p>Users can request an OTP to their registered email and reset their password securely.</p></div>
    <div class="feature-card"><h3>Login and Register</h3><p>Uses bcrypt password hashing and SQLite user storage for a complete authentication workflow.</p></div>
    <div class="feature-card"><h3>Local Gallery</h3><p>Saves generated images and metadata locally, then reloads them in a gallery connected to the logged-in user.</p></div>
    <div class="feature-card"><h3>Admin Dashboard</h3><p>The admin account can view registered users, email verification status, login counts, and recent login entries.</p></div>
    <div class="feature-card"><h3>Colab T4 Ready</h3><p>The SDXL model is intended to run on Google Colab with a T4 GPU for faster image generation.</p></div>
  </div>
</div>
"""

ABOUT_MD = """
<div class="section">
  <h2>ABOUT THE MODEL</h2>
  <p>Stable Diffusion XL is a diffusion-based text-to-image model that transforms natural language prompts into detailed images. This project wraps SDXL inside a secure Gradio web application with OTP-based account verification, password reset, saved image history, and an admin dashboard.</p>
</div>

### Main image parameters
<div class="info-table">
<table>
<tr><th>Parameter</th><th>Purpose</th><th>Recommended Value</th></tr>
<tr><td>Prompt</td><td>Describes the image to generate.</td><td>Detailed, specific text</td></tr>
<tr><td>Negative Prompt</td><td>Describes what to avoid.</td><td>blurry, low quality, distorted</td></tr>
<tr><td>Width and Height</td><td>Controls image size.</td><td>768 or 1024 on GPU</td></tr>
<tr><td>Steps</td><td>Number of denoising iterations.</td><td>20 to 30</td></tr>
<tr><td>Guidance Scale</td><td>How strongly the prompt is followed.</td><td>7 to 8</td></tr>
<tr><td>Seed</td><td>Controls reproducibility.</td><td>-1 for random</td></tr>
<tr><td>Scheduler</td><td>Denoising strategy.</td><td>DPM++ or Euler A</td></tr>
</table>
</div>

### Future scope
The project can be expanded with image-to-image generation, prompt templates, user profile pages, role-based permissions, cloud database deployment, and production hosting.
"""

def session_logged_in(session):
    return bool(session and session.get("user_id"))


def status_text(session=None):
    if session_logged_in(session):
        return f"<div class='status-pill'>Signed in as {session['username']}</div>"
    return "<div class='status-pill'>Log in to generate images, save gallery items, and manage your account securely.</div>"


def handle_register(username, email, password, confirm):
    success, msg = register(username, email, password, confirm)
    return msg, "" if success else password, "" if success else confirm


def handle_login(username, password):
    success, msg, signed_in_user = authenticate_user(username, password)
    session = {"user_id": None, "username": None, "is_admin": False}
    if success:
        session = signed_in_user
        if session.get("is_admin"):
            rows = get_registered_users()
            logins = get_recent_logins()
            return (
                msg,
                status_text(session),
                session,
                gr.update(visible=True),
                rows,
                logins,
                f"Admin access granted for {session['username']}.",
            )
    return msg, status_text(session), session, gr.update(visible=False), gr.update(value=[]), gr.update(value=[]), ""


def handle_logout():
    session = {"user_id": None, "username": None, "is_admin": False}
    return "Logged out successfully.", status_text(session), session, gr.update(visible=False), gr.update(value=[]), gr.update(value=[]), ""


def handle_password_reset_request(identifier):
    return request_password_reset(identifier)


def handle_password_reset(identifier, code, new_password, confirm_password):
    return reset_password(identifier, code, new_password, confirm_password)


def handle_verify_email(identifier, code):
    return verify_email(identifier, code)


def handle_resend_verification(identifier):
    return resend_verification_otp(identifier)


def handle_load_model(session):
    if not session_logged_in(session):
        return "Please log in before loading the image model."
    return generator.load_model()


def handle_generate(prompt, negative_prompt, width, height, steps, guidance, scheduler, seed, save, session):
    if not session_logged_in(session):
        return None, "Please log in first.", ""
    try:
        seed_value = None if int(seed) == -1 else int(seed)
        image, metadata = generator.generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            guidance_scale=guidance,
            scheduler=scheduler,
            seed=seed_value,
        )

        saved_path = ""
        if save:
            saved_path = generator.save_image(image, metadata, session["user_id"])
            save_generation(session["user_id"], metadata, saved_path)

        info = (
            f"Prompt: {metadata['prompt']}\n"
            f"Size: {metadata['width']} x {metadata['height']}\n"
            f"Steps: {metadata['steps']} | Guidance: {metadata['guidance_scale']}\n"
            f"Scheduler: {metadata['scheduler']} | Seed: {metadata['seed']}\n"
            f"Time: {metadata['generation_time']} seconds | Device: {metadata['device']}"
        )
        return image, info, saved_path
    except Exception as e:
        return None, f"Error: {str(e)}", ""


def handle_gallery(session):
    if not session_logged_in(session):
        return []

    rows = get_user_history(session["user_id"])
    images = []
    for prompt, path, seed, created_at in rows:
        try:
            if path and os.path.exists(path):
                img = Image.open(path)
                label = f"{prompt[:55]} | seed {seed} | {created_at}"
                images.append((img, label))
        except Exception:
            continue
    return images


def handle_admin_refresh(session):
    if not session_logged_in(session) or not session.get("is_admin"):
        return "Admin access is not available for this user.", gr.update(value=[]), gr.update(value=[])
    rows = get_registered_users()
    logins = get_recent_logins()
    return f"{len(rows)} registered user(s) found.", rows, logins


with gr.Blocks(title="Secure GenAI Text-to-Image Studio", theme=gr.themes.Soft(), css=APP_CSS) as app:
    gr.HTML(HOME_MD)
    user_status = gr.HTML(status_text())
    session_state = gr.State({"user_id": None, "username": None, "is_admin": False})

    with gr.Tabs():
        with gr.Tab("Generate Image"):
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("## High-Level Text to Image")
                    load_btn = gr.Button("Load SDXL Image Model", variant="primary")
                    load_status = gr.Textbox(label="Model Status", lines=2, interactive=False)
                    prompt = gr.Textbox(
                        label="Prompt",
                        lines=5,
                        placeholder="Example: cinematic cyberpunk city at night, neon reflections, rain, ultra detailed, 8k",
                    )
                    neg_prompt = gr.Textbox(
                        label="Negative Prompt",
                        lines=3,
                        value="blurry, low quality, distorted, extra fingers, bad anatomy, watermark",
                    )
                    gen_btn = gr.Button("Generate Image", variant="primary", size="lg")
                    gr.Examples(
                        examples=[
                            ["a royal portrait of an Indian queen, detailed jewelry, studio lighting, photorealistic"],
                            ["a cyberpunk city skyline at night, neon signs, rain, cinematic"],
                            ["a fantasy dragon flying over a castle, dramatic clouds, ultra detailed"],
                        ],
                        inputs=prompt,
                    )

                with gr.Column(scale=1):
                    gr.Markdown("## Image Controls")
                    width = gr.Slider(512, 1024, 768, step=128, label="Width")
                    height = gr.Slider(512, 1024, 768, step=128, label="Height")
                    steps = gr.Slider(10, 50, 25, step=1, label="Steps")
                    guidance = gr.Slider(1.0, 15.0, 7.5, step=0.5, label="Guidance Scale")
                    scheduler = gr.Dropdown(choices=list(SCHEDULERS.keys()), value="dpm++", label="Scheduler")
                    seed = gr.Number(value=-1, label="Seed (-1 means random)")
                    save_img = gr.Checkbox(value=True, label="Save image and metadata")

            with gr.Row():
                output_img = gr.Image(label="Generated Image", type="pil", height=520)
                with gr.Column():
                    output_info = gr.Textbox(label="Generation Info", lines=9, interactive=False)
                    output_path = gr.Textbox(label="Saved Path", interactive=False)

        with gr.Tab("Gallery"):
            gr.Markdown("## Saved Generations\nRefresh to load images saved under your account.")
            refresh_btn = gr.Button("Refresh Gallery", variant="primary")
            gallery = gr.Gallery(label="Your Generations", columns=3, object_fit="contain", height="auto")

        with gr.Tab("Admin", visible=False) as admin_tab:
            gr.Markdown("## Admin Dashboard\nThis tab appears only after an admin account signs in.")
            admin_btn = gr.Button("Refresh Registered Users", variant="primary")
            admin_status = gr.Textbox(label="Admin Status", interactive=False)
            admin_users = gr.Dataframe(
                headers=["User ID", "Username", "Email", "Registered At", "Role", "Email Status", "Images", "Last Login", "Login Count"],
                datatype=["number", "str", "str", "str", "str", "str", "number", "str", "number"],
                label="Registered Users",
                interactive=False,
            )
            admin_logins = gr.Dataframe(
                headers=["Username", "Login Time"],
                datatype=["str", "str"],
                label="Recent Logins",
                interactive=False,
            )

        with gr.Tab("Examples"):
            gr.HTML(examples_html())

        with gr.Tab("Features"):
            gr.HTML(FEATURES_MD)

        with gr.Tab("Sign In / OTP"):
            gr.Markdown("## Sign In")
            login_user = gr.Textbox(label="Username", placeholder="Enter your username")
            login_pass = gr.Textbox(label="Password", type="password", placeholder="Enter your password")
            login_btn = gr.Button("Sign In", variant="primary")
            login_msg = gr.Textbox(label="Login Status", interactive=False)
            with gr.Accordion("Verify Email OTP", open=True):
                gr.Markdown("If login asks you to verify your email, enter the OTP sent to your registered email here.")
                with gr.Row():
                    with gr.Column(scale=1):
                        signin_verify_identifier = gr.Textbox(label="Username or Email")
                        signin_verify_code = gr.Textbox(label="Verification OTP")
                    with gr.Column(scale=1):
                        signin_verify_btn = gr.Button("Verify Email", variant="primary")
                        signin_resend_verify_btn = gr.Button("Resend Verification OTP", variant="secondary")
                        signin_verify_status = gr.Textbox(label="Verification Status", interactive=False)
            with gr.Accordion("Forgot Password", open=False):
                gr.Markdown("Enter your username or email to receive a reset code, then use that code to set a new password.")
                with gr.Row():
                    with gr.Column(scale=1):
                        reset_identifier = gr.Textbox(label="Username or Email")
                        reset_send_btn = gr.Button("Send Reset Code", variant="primary")
                        reset_send_status = gr.Textbox(label="Email Status", interactive=False)
                    with gr.Column(scale=1):
                        reset_code = gr.Textbox(label="Reset Code")
                        reset_new_password = gr.Textbox(label="New Password", type="password")
                        reset_confirm_password = gr.Textbox(label="Confirm New Password", type="password")
                        reset_btn = gr.Button("Reset Password", variant="primary")
                        reset_status = gr.Textbox(label="Reset Status", interactive=False)

        with gr.Tab("Register"):
            gr.Markdown("## Create Account")
            reg_user = gr.Textbox(label="Username", placeholder="Minimum 3 characters")
            reg_email = gr.Textbox(label="Email", placeholder="name@example.com")
            reg_pass = gr.Textbox(label="Password", type="password", placeholder="Minimum 6 characters")
            reg_confirm = gr.Textbox(label="Confirm Password", type="password")
            reg_btn = gr.Button("Register", variant="primary")
            reg_msg = gr.Textbox(label="Registration Status", interactive=False)
            gr.Markdown("## Verify Registration OTP\nAfter registration, enter the OTP sent to your email here.")
            reg_verify_identifier = gr.Textbox(label="Username or Email")
            reg_verify_code = gr.Textbox(label="Verification OTP")
            reg_verify_btn = gr.Button("Verify Email OTP", variant="primary")
            reg_resend_verify_btn = gr.Button("Resend OTP", variant="secondary")
            reg_verify_status = gr.Textbox(label="OTP Verification Status", interactive=False)

        with gr.Tab("OTP Verification"):
            gr.Markdown("## OTP Verification\nUse this page if the app says you must verify your email before signing in.")
            verify_identifier = gr.Textbox(label="Username or Email")
            verify_code = gr.Textbox(label="Verification OTP")
            verify_btn = gr.Button("Verify Email", variant="primary")
            resend_verify_btn = gr.Button("Resend Verification OTP", variant="secondary")
            verify_status = gr.Textbox(label="Verification Status", interactive=False)

        with gr.Tab("About"):
            gr.Markdown(ABOUT_MD)

    logout_btn = gr.Button("Logout", variant="secondary")
    logout_msg = gr.Textbox(label="Session Status", interactive=False)

    reg_btn.click(handle_register, inputs=[reg_user, reg_email, reg_pass, reg_confirm], outputs=[reg_msg, reg_pass, reg_confirm])
    signin_verify_btn.click(handle_verify_email, inputs=[signin_verify_identifier, signin_verify_code], outputs=signin_verify_status)
    signin_resend_verify_btn.click(handle_resend_verification, inputs=signin_verify_identifier, outputs=signin_verify_status)
    reg_verify_btn.click(handle_verify_email, inputs=[reg_verify_identifier, reg_verify_code], outputs=reg_verify_status)
    reg_resend_verify_btn.click(handle_resend_verification, inputs=reg_verify_identifier, outputs=reg_verify_status)
    verify_btn.click(handle_verify_email, inputs=[verify_identifier, verify_code], outputs=verify_status)
    resend_verify_btn.click(handle_resend_verification, inputs=verify_identifier, outputs=verify_status)
    login_btn.click(
        handle_login,
        inputs=[login_user, login_pass],
        outputs=[login_msg, user_status, session_state, admin_tab, admin_users, admin_logins, admin_status],
    )
    reset_send_btn.click(handle_password_reset_request, inputs=reset_identifier, outputs=reset_send_status)
    reset_btn.click(
        handle_password_reset,
        inputs=[reset_identifier, reset_code, reset_new_password, reset_confirm_password],
        outputs=reset_status,
    )
    logout_btn.click(
        handle_logout,
        outputs=[logout_msg, user_status, session_state, admin_tab, admin_users, admin_logins, admin_status],
    )
    load_btn.click(handle_load_model, inputs=session_state, outputs=load_status)
    gen_btn.click(
        handle_generate,
        inputs=[prompt, neg_prompt, width, height, steps, guidance, scheduler, seed, save_img, session_state],
        outputs=[output_img, output_info, output_path],
    )
    refresh_btn.click(handle_gallery, inputs=session_state, outputs=gallery)
    admin_btn.click(handle_admin_refresh, inputs=session_state, outputs=[admin_status, admin_users, admin_logins])


if __name__ == "__main__":
    try:
        import google.colab  # noqa: F401

        app.launch(share=True, debug=True)
    except Exception:
        app.launch(server_name="127.0.0.1", server_port=7860, share=False, inbrowser=True)



