import os
import requests
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

def send_line_notify(message, attachment_path=None):
    token = os.getenv("LINE_ACCESS_TOKEN")
    if not token:
        print("LINE_ACCESS_TOKEN not set. Skipping LINE notification.")
        return

    url = "https://notify-api.line.me/api/notify"
    headers = {"Authorization": "Bearer " + token}
    payload = {"message": message}
    files = {}

    if attachment_path and os.path.exists(attachment_path):
        # LINE Notify doesn't strictly support generic file attachments like PDFs in the same way as images
        # The 'imageFile' param is for images.
        # However, many users want to send PDFs. LINE Notify API officially only supports images.
        # Fallback: Send a link if it was hosted, or just text.
        # Wait, strictly speaking LINE Notify API does NOT support generic document uploads.
        # Limitless use case: Maybe text summary + "Check your email/folder" is best for LINE?
        # Or if the user really wants PDF on LINE, we might need Messaging API (complex) or just fail gracefully.
        # Let's try sending it as imageFile just in case it works? No, it validates format.
        # We will warn the user in the message that PDF sending via LINE Notify isn't directly supported 
        # for non-images, or check if we can convert first page to image? Too complex.
        # Strategy: Send text summary to LINE. Send PDF to Email.
        pass

    try:
        response = requests.post(url, headers=headers, data=payload) #, files=files)
        if response.status_code == 200:
            print("Successfully sent LINE notification.")
        else:
            print(f"Failed to send LINE notification. Status: {response.status_code}")
    except Exception as e:
        print(f"Error sending LINE notification: {e}")

def send_email(subject, body, attachment_path=None):
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    receiver = os.getenv("EMAIL_RECEIVER")

    if not all([sender, password, receiver]):
        print("Email commands not fully set. Skipping Email.")
        return

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = receiver
    msg.set_content(body)

    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, 'rb') as f:
            file_data = f.read()
            file_name = os.path.basename(attachment_path)
        
        msg.add_attachment(file_data, maintype='application', subtype='pdf', filename=file_name)

    try:
        # Assuming Gmail for now (standard port 465 SSL or 587 TLS)
        # Using 465 SSL safely
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(sender, password)
            smtp.send_message(msg)
        print("Successfully sent Email.")
    except Exception as e:
        print(f"Error sending Email: {e}")

if __name__ == "__main__":
    # Test
    # send_line_notify("Test message from Python")
    # send_email("Test Subject", "Test Body", "test.pdf")
    pass
