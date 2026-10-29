
import os
import smtplib
from pathlib import Path
from email.message import EmailMessage
from dotenv import load_dotenv

# Load .env from the same folder as this Python file
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

username = os.getenv("MAIL_USERNAME", "").strip()
password = os.getenv("MAIL_PASSWORD", "").replace(" ", "")
mail_from = os.getenv("MAIL_FROM", username).strip()
server_name = os.getenv("MAIL_SERVER", "smtp.gmail.com").strip()
port = int(os.getenv("MAIL_PORT", "587"))

print("Username loaded:", username[:3] + "***" if username else "MISSING")
print("Password loaded:", "YES" if password else "NO")
print("Password length:", len(password))
print("SMTP server:", server_name)
print("SMTP port:", port)

if not username or not password:
    raise ValueError(
        "MAIL_USERNAME or MAIL_PASSWORD is missing from .env"
    )

message = EmailMessage()
message["Subject"] = "EduVision OTP Email Test"
message["From"] = mail_from
message["To"] = username
message.set_content(
    "EduVision email configuration is working correctly."
)

try:
    print("Connecting to Gmail SMTP...")

    with smtplib.SMTP(server_name, port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()

        print("Secure connection established.")
        print("Logging in to Gmail...")

        server.login(username, password)

        print("Login successful. Sending test email...")
        server.send_message(message)

    print("SUCCESS: Test email sent. Check your inbox.")

except smtplib.SMTPAuthenticationError:
    print("LOGIN FAILED: Gmail rejected the credentials.")
    print("Check MAIL_USERNAME and your Google App Password.")

except (smtplib.SMTPException, OSError) as error:
    print("EMAIL TEST FAILED:", type(error).__name__)
    print("Details:", str(error))
