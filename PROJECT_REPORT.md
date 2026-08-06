# Project Report: Secure GenAI Text-to-Image Studio

## Abstract

Secure GenAI Text-to-Image Studio is a dynamic web application that generates images from text prompts using Stable Diffusion XL. The system includes secure registration, login, email OTP verification, forgot-password OTP reset, user image history, and an admin dashboard for monitoring registered users and login activity.

## Aim

The aim of this project is to create a complete text-to-image generation website that combines generative AI functionality with a secure user-management system.

## Objectives

- Generate high-quality images from user prompts.
- Store user accounts securely with hashed passwords.
- Verify user emails using OTP.
- Reset forgotten passwords using OTP sent to registered email.
- Save generated image history per user.
- Provide an admin dashboard for user and login monitoring.
- Run reliably on Google Colab with a T4 GPU.

## Methodology

The application uses Gradio for the web interface, Diffusers for Stable Diffusion XL image generation, SQLite for data storage, bcrypt for password hashing, and SMTP email for OTP delivery. The database stores users, image generations, password reset codes, email verification codes, and login events.

## Modules

- `app.py`: Main application and Gradio UI.
- `model_vscode.py`: SDXL loading and image generation logic.
- `auth_vscode.py`: Registration, login, OTP verification, password reset, and admin setup.
- `database_vscode.py`: Database tables, queries, and persistence logic.
- `frontend/home.html`: Landing page HTML.
- `frontend/style.css`: Custom interface styling.

## Security

The project uses bcrypt password hashing, email OTP verification, OTP password reset, admin-only dashboard visibility, per-browser Gradio session state, and SQLite WAL mode for better concurrent access.

## Result

The completed project provides a working image-generation website where users can register, verify email, log in, generate images, save generated outputs, and view their personal gallery. The admin can view registered users and recent login events.

## Future Scope

Future improvements may include image-to-image generation, prompt templates, cloud database deployment, production hosting, profile management, and stronger role-based access control.
