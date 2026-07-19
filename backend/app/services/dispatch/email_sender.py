"""SMTP email dispatch — works with Microsoft 365, Google Workspace, Zimbra,
or any standard SMTP endpoint configured in Settings.

Common host presets (surfaced in the Settings UI as a dropdown):
  Microsoft 365 : smtp.office365.com : 587 (STARTTLS)
  Google        : smtp.gmail.com     : 587 (STARTTLS)
  Zimbra        : your-zimbra-host   : 587/465
"""
import hashlib
import hmac
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from ...config import get_settings
from ...models.entities import Certificate, OrgSettings


def sign_job_id(job_id: int) -> str:
    settings = get_settings()
    return hmac.new(
        settings.link_signing_secret.encode(),
        f"job:{job_id}".encode(),
        hashlib.sha256,
    ).hexdigest()[:24]


def verify_job_sig(job_id: int, sig: str) -> bool:
    return hmac.compare_digest(sign_job_id(job_id), sig)


def tracking_pixel_url(job_id: int) -> str:
    settings = get_settings()
    return f"{settings.public_base_url}/public/track/{job_id}.png?sig={sign_job_id(job_id)}"


def _smtp_config(org: OrgSettings) -> tuple[str, int, str]:
    host = (org.smtp_host or "").strip()
    sender = (org.smtp_from or org.smtp_user or org.officer_email or "").strip()
    if not (host and sender):
        raise RuntimeError("SMTP is not configured in Settings")
    return host, int(org.smtp_port or 587), sender


def _send_message(org: OrgSettings, msg: EmailMessage) -> None:
    host, port, _ = _smtp_config(org)
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
        try:
            if org.smtp_use_tls and port != 465:
                server.starttls()
            if org.smtp_user:
                server.login(org.smtp_user.strip(), org.smtp_password or "")
            server.send_message(msg)
        finally:
            server.quit()
    except smtplib.SMTPAuthenticationError as exc:
        detail = exc.smtp_error.decode(errors="replace") if isinstance(exc.smtp_error, bytes) else exc.smtp_error
        if "Application-specific password required" in str(detail):
            raise RuntimeError(
                "Gmail requires an App Password for SMTP. Create a Google App Password "
                "and enter it in Settings instead of your normal Gmail password."
            ) from exc
        raise RuntimeError(f"SMTP authentication failed: {detail}") from exc
    except smtplib.SMTPConnectError as exc:
        raise RuntimeError(f"Could not connect to SMTP server: {exc}") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise RuntimeError(f"SMTP refused recipient: {exc.recipients}") from exc
    except smtplib.SMTPSenderRefused as exc:
        raise RuntimeError(f"SMTP refused sender address {exc.sender}: {exc.smtp_error}") from exc
    except smtplib.SMTPException as exc:
        raise RuntimeError(f"SMTP error: {exc}") from exc
    except OSError as exc:
        raise RuntimeError(f"SMTP connection failed: {exc}") from exc


def send_certificate_email(org: OrgSettings, cert: Certificate, recipient: str, job_id: int) -> None:
    _, _, sender = _smtp_config(org)
    if not cert.pdf_data:
        raise RuntimeError("Certificate PDF has not been rendered")

    text_body = (
        f"Dear {cert.supplier.name},\n\n"
        f"Please find attached the Certificate of Deduction of Tax "
        f"({cert.certificate_no}) for the period {cert.period}.\n\n"
        f"Regards,\n{org.officer_name or ''}\n{org.officer_designation or ''}"
    )

    msg = EmailMessage()
    msg["Subject"] = f"Tax Deduction Certificate {cert.certificate_no}"
    msg["From"] = formataddr((org.company_name or "", sender))
    msg["To"] = recipient
    msg.set_content(text_body)

    # The org logo/signature is embedded via a per-dispatch tracking URL: when
    # the recipient's mail client loads it, /public/track marks this job read.
    html_paragraphs = "".join(f"<p>{line}</p>" for line in text_body.split("\n\n"))
    html_body = (
        html_paragraphs
        + f'<img src="{tracking_pixel_url(job_id)}" alt="" width="120">'
    )
    msg.add_alternative(html_body, subtype="html")

    safe_no = (cert.certificate_no or f"cert-{cert.id}").replace("/", "_")
    msg.add_attachment(
        cert.pdf_data, maintype="application", subtype="pdf",
        filename=f"{safe_no}.pdf",
    )

    _send_message(org, msg)


def send_test_email(org: OrgSettings, recipient: str | None = None) -> str:
    _, _, sender = _smtp_config(org)
    to_addr = (recipient or org.officer_email or sender).strip()
    if not to_addr:
        raise RuntimeError("Enter an officer email or from address for the test email")

    msg = EmailMessage()
    msg["Subject"] = "Tax Certificate SMTP test"
    msg["From"] = formataddr((org.company_name or "", sender))
    msg["To"] = to_addr
    msg.set_content(
        "SMTP is configured correctly for the Tax Deduction Certificate module.\n\n"
        "You can now send certificate PDFs from Certificate Issue."
    )
    _send_message(org, msg)
    return to_addr
