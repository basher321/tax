"""SMTP email dispatch — works with Microsoft 365, Google Workspace, Zimbra,
or any standard SMTP endpoint configured in Settings.

Common host presets (surfaced in the Settings UI as a dropdown):
  Microsoft 365 : smtp.office365.com : 587 (STARTTLS)
  Google        : smtp.gmail.com     : 587 (STARTTLS)
  Zimbra        : your-zimbra-host   : 587/465
"""
import os
import smtplib
from email.message import EmailMessage

from ...models.entities import Certificate, OrgSettings


def send_certificate_email(org: OrgSettings, cert: Certificate, recipient: str) -> None:
    if not (org.smtp_host and org.smtp_from):
        raise RuntimeError("SMTP is not configured in Settings")
    if not cert.pdf_path or not os.path.exists(cert.pdf_path):
        raise RuntimeError("Certificate PDF has not been rendered")

    msg = EmailMessage()
    msg["Subject"] = f"Tax Deduction Certificate {cert.certificate_no}"
    msg["From"] = org.smtp_from
    msg["To"] = recipient
    msg.set_content(
        f"Dear {cert.supplier.name},\n\n"
        f"Please find attached the Certificate of Deduction of Tax "
        f"({cert.certificate_no}) for the period {cert.period}.\n\n"
        f"Regards,\n{org.officer_name or ''}\n{org.officer_designation or ''}"
    )
    with open(cert.pdf_path, "rb") as f:
        msg.add_attachment(
            f.read(), maintype="application", subtype="pdf",
            filename=os.path.basename(cert.pdf_path),
        )

    port = org.smtp_port or 587
    if port == 465:
        server = smtplib.SMTP_SSL(org.smtp_host, port, timeout=30)
    else:
        server = smtplib.SMTP(org.smtp_host, port, timeout=30)
    try:
        if org.smtp_use_tls and port != 465:
            server.starttls()
        if org.smtp_user:
            server.login(org.smtp_user, org.smtp_password or "")
        server.send_message(msg)
    finally:
        server.quit()
