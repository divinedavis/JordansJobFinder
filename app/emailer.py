import smtplib
from email.message import EmailMessage

from flask import current_app


def send_magic_link_email(recipient: str, magic_link: str) -> bool:
    host = current_app.config["SMTP_HOST"]
    from_email = current_app.config["SMTP_FROM_EMAIL"]
    if not host or not from_email:
        current_app.logger.info("Magic link for %s: %s", recipient, magic_link)
        return False

    message = EmailMessage()
    message["Subject"] = "Your Jordan's Job Finder sign-in link"
    message["From"] = from_email
    message["To"] = recipient
    message.set_content(
        "Use this secure sign-in link to access your Jordan's Job Finder account:\n\n"
        f"{magic_link}\n\n"
        "This link expires in 20 minutes."
    )

    with smtplib.SMTP(host, current_app.config["SMTP_PORT"]) as server:
        server.starttls()
        if current_app.config["SMTP_USERNAME"]:
            server.login(
                current_app.config["SMTP_USERNAME"],
                current_app.config["SMTP_PASSWORD"],
            )
        server.send_message(message)
    return True
