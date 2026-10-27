import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import httpx

load_dotenv()

logger = logging.getLogger(__name__)


def send_otp_email(recipient_email: str, otp_code: str, validity_minutes: int = 10) -> bool:
    """
    Sends the 6-digit OTP code to the recipient using:
    1. Brevo REST API (if BREVO_API_KEY is configured in .env)
    2. Standard SMTP (if SMTP_USER and SMTP_PASSWORD are configured in .env)
    3. Console log fallback (in local dev / offline mode)
    """
    brevo_api_key = os.getenv("BREVO_API_KEY")
    from_email = os.getenv("DEFAULT_FROM_EMAIL", "noreply@ask-ai.com")

    subject = "Your ASK-AI Verification Code"
    body = (
        f"Hi {recipient_email},\n\n"
        f"Your verification code is: {otp_code}\n"
        f"This code expires in {validity_minutes} minutes.\n\n"
        f"If you didn't request this code, you can safely ignore this email.\n\n"
        f"— The ASK-AI Team"
    )

    # 1. Brevo REST API dispatch
    if brevo_api_key:
        try:
            url = "https://api.brevo.com/v3/smtp/email"
            headers = {
                "accept": "application/json",
                "api-key": brevo_api_key,
                "content-type": "application/json",
            }
            payload = {
                "sender": {"name": "ASK-AI", "email": from_email},
                "to": [{"email": recipient_email}],
                "subject": subject,
                "textContent": body,
            }
            with httpx.Client(timeout=10) as client:
                res = client.post(url, headers=headers, json=payload)
                if res.status_code in (200, 201):
                    logger.info(f"Successfully sent OTP email via Brevo API to {recipient_email}")
                    return True
                else:
                    logger.error(f"Brevo API error: {res.status_code} - {res.text}")
                    print(f"[BREVO ERROR] {res.status_code}: {res.text}. Fallback OTP code is {otp_code}")
                    return False
        except Exception as exc:
            logger.error(f"Failed to send email via Brevo API: {exc}")
            print(f"[BREVO API ERROR] {exc}. Fallback OTP code is {otp_code}")
            return False

    # 2. SMTP dispatch
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_use_tls = os.getenv("SMTP_USE_TLS", "True").lower() == "true"
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")

    # If neither Brevo nor SMTP credentials are provided, print code in dev mode
    if not smtp_user or not smtp_password:
        logger.warning(
            f"[DEV MODE / NO EMAIL CREDENTIALS] OTP email to {recipient_email}: code = {otp_code}"
        )
        print(f"\n[DEV MODE OTP] Email: {recipient_email} | Code: {otp_code}\n")
        return True

    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
            if smtp_use_tls:
                server.starttls()

        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        logger.info(f"Successfully sent OTP email to {recipient_email}")
        return True
    except Exception as exc:
        logger.error(f"Failed to send OTP email via SMTP to {recipient_email}: {exc}")
        # Print for local debugging so developer isn't locked out
        print(f"[SMTP ERROR] Failed to send to {recipient_email}: {exc}. Fallback OTP code is {otp_code}")
        return False
