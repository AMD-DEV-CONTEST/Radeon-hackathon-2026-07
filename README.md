# Secure GenAI Text-to-Image Studio

This is a Google Colab-ready dynamic web application for secure text-to-image generation using Stable Diffusion XL. It includes registration, login, email OTP verification, forgot-password OTP reset, saved image history, and an admin dashboard.

## Main Features

- Text-to-image generation with SDXL.
- Secure registration and login with bcrypt password hashing.
- Email OTP verification after registration.
- Forgot password flow with OTP sent to the registered email.
- SQLite database with persistent user, login, OTP, and generation records.
- Admin dashboard for viewing registered users, email verification status, login counts, and recent login entries.
- User gallery for saved generated images.
- Separate frontend files in the `frontend` folder.

## Project Files

- `app.py` - Main Gradio web application.
- `model_vscode.py` - SDXL model loading and image generation logic.
- `auth_vscode.py` - Authentication, OTP email, password reset, and admin setup.
- `database_vscode.py` - SQLite database setup and queries.
- `frontend/home.html` - Landing page HTML.
- `frontend/style.css` - Custom frontend styling.
- `requirements_vscode.txt` - Python dependencies.
- `.env.example` - Example email/admin environment variables.

## Run on Google Colab

1. Open Google Colab.
2. Go to `Runtime > Change runtime type`.
3. Select `T4 GPU`.
4. Click `Save`.
5. Upload the project zip.

Use these cells:

```python
import os
os.chdir("/content")
print(os.getcwd())
```

```python
from google.colab import files
uploaded = files.upload()
```

Upload:

```text
secure_text_to_image_colab.zip
```

Then run:

```python
import os
os.chdir("/content")
print(os.listdir("/content"))
```

```python
!rm -rf /content/secure_text_to_image
!unzip -q /content/secure_text_to_image_colab.zip -d /content/secure_text_to_image
os.chdir("/content/secure_text_to_image")
print(os.getcwd())
print(os.listdir())
```

Install dependencies:

```python
!pip install -r requirements_vscode.txt
```

Run the app:

```python
!python app.py
```

Open the public Gradio link shown by Colab.

## Admin Login

Default admin credentials:

```text
Username: admin
Password: Gnk2005/09-07
```

The admin dashboard appears only after the admin account signs in.

## Email OTP Setup

Forgot password and registration verification require SMTP email settings.

Create a `.env` file in the project folder with:

```text
GENAI_SMTP_HOST=smtp.gmail.com
GENAI_SMTP_PORT=587
GENAI_SMTP_USER=your_email@gmail.com
GENAI_SMTP_PASSWORD=your_16_character_gmail_app_password
GENAI_SMTP_FROM=your_email@gmail.com
GENAI_ADMIN_PASSWORD=Gnk2005/09-07
```

For Gmail, use a Gmail App Password, not your normal Gmail password.

## Database Storage

When running in Colab, the app attempts to use Google Drive:

```text
/content/drive/MyDrive/done_project/data/app.db
```

This keeps users, OTP records, login history, and image history saved even after the Colab runtime restarts.

## Notes

- SDXL is heavy and should be run with a Colab T4 GPU.
- If image generation is slow, reduce width, height, or steps.
- If OTP email does not send, check the `.env` values and Gmail App Password.
