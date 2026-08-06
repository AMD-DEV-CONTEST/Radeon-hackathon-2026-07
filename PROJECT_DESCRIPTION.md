# Project Description

## Title

Secure GenAI Text-to-Image Studio

## Overview

Secure GenAI Text-to-Image Studio is a dynamic AI web application that converts text prompts into generated images using Stable Diffusion XL. The project is designed to run on Google Colab with a T4 GPU and provides a complete user-facing website experience with authentication, OTP email security, saved image history, and admin monitoring.

## Objective

The objective of this project is to build a full working text-to-image generation website where users can register, verify their email, log in, generate AI images, save their work, and view their generation history. The admin can securely monitor registered users and login activity without user sessions overriding each other.

## Core Modules

1. Frontend interface:
   The project uses Gradio with separate HTML and CSS frontend files. The landing page introduces the model and shows an attractive image-generation focused interface.

2. Authentication:
   Users can register and log in securely. Passwords are hashed using bcrypt before storage.

3. Email OTP verification:
   After registration, users receive an OTP on their registered email. Normal users must verify their email before signing in.

4. Forgot password:
   If a user forgets their password, the system sends a reset OTP to the registered email. The user can then reset the password securely.

5. Text-to-image generation:
   The app uses Stable Diffusion XL through Diffusers. Users can control prompt, negative prompt, width, height, steps, guidance scale, scheduler, and seed.

6. Image gallery:
   Generated images can be saved with metadata and reloaded from the user gallery.

7. Admin dashboard:
   The admin can view registered users, email verification status, login counts, and recent login events. Admin data remains saved in the SQLite database after logout and login.

## Technology Stack

- Python
- Gradio
- Diffusers
- Transformers
- PyTorch
- Stable Diffusion XL
- SQLite
- bcrypt
- Pillow
- Google Colab T4 GPU

## Security Features

- bcrypt password hashing.
- Email OTP verification after registration.
- OTP-based password reset.
- Admin-only dashboard visibility.
- Per-session Gradio state to avoid one user overriding another user's login.
- SQLite WAL mode and busy timeout for more reliable database access with multiple users.

## Expected Output

The final output is a web application where:

- Users can create accounts.
- Users can verify email through OTP.
- Users can log in and generate AI images.
- Generated images can be saved and viewed in a gallery.
- Forgot-password OTP reset works through the registered email.
- Admin can view user and login entries dynamically.

## Future Scope

- Add image-to-image generation.
- Add prompt templates and style presets.
- Add cloud database hosting.
- Add production deployment with a dedicated backend framework.
- Add user profile pages and stronger role-based permissions.
