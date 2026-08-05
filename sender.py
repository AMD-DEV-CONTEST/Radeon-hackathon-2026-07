import os
import smtplib
import base64
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
from dotenv import load_dotenv
import db

# Load environment variables
load_dotenv()

def refresh_google_token(token_info, user_id=1, db_path="outreach.db"):
    """
    Refreshes the Google OAuth access token using the stored refresh token.
    """
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError("Google Client ID or Client Secret is not set in environment variables.")
        
    refresh_token = token_info["refresh_token"]
    token_url = "https://oauth2.googleapis.com/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }
    
    response = requests.post(token_url, data=payload)
    if response.status_code != 200:
        raise Exception(f"Failed to refresh Google token: {response.text}")
        
    res_data = response.json()
    new_access_token = res_data["access_token"]
    expires_in = res_data.get("expires_in", 3600)
    
    # Calculate new expiration time
    new_expires_at = (datetime.now() + timedelta(seconds=expires_in)).isoformat()
    
    # Update in database
    db.save_oauth_tokens(
        provider="google",
        email=token_info["email"],
        access_token=new_access_token,
        refresh_token=refresh_token,
        expires_at=new_expires_at,
        user_id=user_id,
        db_path=db_path
    )
    
    return new_access_token

def send_google_oauth_email(to_email, subject, body, user_id=1, attachment_path=None, db_path="outreach.db"):
    """
    Sends an email using Google Gmail API with OAuth 2.0.
    """
    token_info = db.get_oauth_tokens("google", user_id=user_id, db_path=db_path)
    if not token_info:
        return False, "Google Account is not connected. Please connect it in the settings page first."
        
    # Check expiration and refresh if needed
    try:
        expires_at = datetime.fromisoformat(token_info["expires_at"])
        if datetime.now() >= expires_at - timedelta(seconds=10):
            access_token = refresh_google_token(token_info, user_id=user_id, db_path=db_path)
        else:
            access_token = token_info["access_token"]
    except Exception as e:
        return False, f"Failed to refresh Google OAuth token: {str(e)}"
        
    # Construct the raw email
    try:
        user_profile = db.get_user_profile(user_id, db_path=db_path)
        full_name = user_profile.get("full_name") if user_profile else None
        user_email = user_profile.get("email") if user_profile else None

        msg = MIMEMultipart()
        if full_name:
            msg["From"] = f'"{full_name}" <{token_info["email"]}>'
        else:
            msg["From"] = token_info["email"]
        msg["To"] = to_email
        msg["Subject"] = subject
        if user_email:
            msg["Reply-To"] = user_email
        
        msg.attach(MIMEText(body, "plain"))
        
        if attachment_path:
            if not os.path.exists(attachment_path):
                return False, f"Attachment file not found at: {attachment_path}"
                
            filename = os.path.basename(attachment_path)
            with open(attachment_path, "rb") as attachment:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(attachment.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename= {filename}",
                )
                msg.attach(part)
                
        # Base64url encode the message bytes as expected by Gmail API
        raw_msg = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    except Exception as e:
        return False, f"Failed to construct email: {str(e)}"
        
    # Send via Gmail API
    send_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "raw": raw_msg
    }
    
    try:
        response = requests.post(send_url, json=payload, headers=headers)
        if response.status_code == 200:
            return True, None
        else:
            return False, f"Gmail API Error: {response.status_code} - {response.text}"
    except Exception as e:
        return False, f"Gmail API Request failed: {str(e)}"

def send_single_email(to_email, subject, body, user_id=1, attachment_path=None, db_path="outreach.db"):
    """
    Sends a single email either via configured Google OAuth 2.0 or SMTP fallback.
    """
    user_profile = db.get_user_profile(user_id, db_path=db_path)
    
    sending_channel = "smtp"
    if user_profile and user_profile.get("sending_channel"):
        sending_channel = user_profile["sending_channel"].lower().strip()
    else:
        sending_channel = os.environ.get("SENDING_CHANNEL", "smtp").lower().strip()
    
    if sending_channel == "google":
        return send_google_oauth_email(to_email, subject, body, user_id, attachment_path, db_path)
        
    # Default: SMTP (Ensure no fallback to global server credentials for user cold outreach)
    sender_email = user_profile.get("sender_email") if user_profile else None
    sender_password = user_profile.get("sender_password") if user_profile else None
    smtp_server = user_profile.get("smtp_server") if user_profile else "smtp.gmail.com"
    smtp_port = user_profile.get("smtp_port") if user_profile else "587"
    
    if not sender_email or not sender_password:
        return False, "Your SMTP Relay Server or App Password is not configured. Please open Connection Settings in the top-right to configure your email."
        
    try:
        smtp_port = int(smtp_port)
    except ValueError:
        return False, f"Invalid SMTP_PORT: {smtp_port}. Must be an integer."
        
    try:
        full_name = user_profile.get("full_name") if user_profile else None
        user_email = user_profile.get("email") if user_profile else None

        msg = MIMEMultipart()
        if full_name:
            msg["From"] = f'"{full_name}" <{sender_email}>'
        else:
            msg["From"] = sender_email
        msg["To"] = to_email
        msg["Subject"] = subject
        if user_email:
            msg["Reply-To"] = user_email
        
        msg.attach(MIMEText(body, "plain"))
        
        if attachment_path:
            if not os.path.exists(attachment_path):
                return False, f"Attachment file not found at: {attachment_path}"
                
            filename = os.path.basename(attachment_path)
            try:
                with open(attachment_path, "rb") as attachment:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(attachment.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename= {filename}",
                    )
                    msg.attach(part)
            except Exception as e:
                return False, f"Failed to attach resume file: {str(e)}"
                
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.ehlo()
            server.starttls()
            server.ehlo()
            
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, to_email, msg.as_string())
        server.quit()
        
        return True, None
        
    except Exception as e:
        return False, f"SMTP Error: {str(e)}"

