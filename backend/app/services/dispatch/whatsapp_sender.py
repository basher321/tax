"""WhatsApp dispatch — WhatsApp Business Cloud API or Twilio.

Both providers require a publicly reachable URL for document messages, so we
send a signed hosted link to the certificate PDF (`/public/certificates/...`)
plus a short text message. The link is HMAC-signed so it can't be enumerated.
"""
import hashlib
import hmac
import re

import httpx

from ...config import get_settings
from ...models.entities import Certificate, OrgSettings


def signed_certificate_url(cert: Certificate) -> str:
    settings = get_settings()
    sig = hmac.new(
        settings.link_signing_secret.encode(),
        f"cert:{cert.id}".encode(),
        hashlib.sha256,
    ).hexdigest()[:24]
    return f"{settings.public_base_url}/public/certificates/{cert.id}?sig={sig}"


def verify_certificate_sig(cert_id: int, sig: str) -> bool:
    settings = get_settings()
    expected = hmac.new(
        settings.link_signing_secret.encode(),
        f"cert:{cert_id}".encode(),
        hashlib.sha256,
    ).hexdigest()[:24]
    return hmac.compare_digest(expected, sig)


def _normalize_phone(phone: str) -> str:
    p = re.sub(r"[\s\-()]", "", phone)
    if not p.startswith("+"):
        p = "+" + p
    return p


def send_certificate_whatsapp(org: OrgSettings, cert: Certificate, recipient: str) -> None:
    phone = _normalize_phone(recipient)
    url = signed_certificate_url(cert)
    body = (
        f"Certificate of Deduction of Tax {cert.certificate_no} "
        f"for period {cert.period}. Download: {url}"
    )

    if org.wa_provider == "twilio":
        if not (org.wa_twilio_sid and org.wa_twilio_auth and org.wa_twilio_from):
            raise RuntimeError("Twilio WhatsApp credentials not configured in Settings")
        resp = httpx.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{org.wa_twilio_sid}/Messages.json",
            auth=(org.wa_twilio_sid, org.wa_twilio_auth),
            data={
                "From": f"whatsapp:{org.wa_twilio_from}",
                "To": f"whatsapp:{phone}",
                "Body": body,
                # Twilio fetches the PDF from the hosted link:
                "MediaUrl": url,
            },
            timeout=30,
        )
        resp.raise_for_status()
    else:  # WhatsApp Business Cloud API
        if not (org.wa_token and org.wa_phone_number_id):
            raise RuntimeError("WhatsApp Cloud API credentials not configured in Settings")
        resp = httpx.post(
            f"https://graph.facebook.com/v20.0/{org.wa_phone_number_id}/messages",
            headers={"Authorization": f"Bearer {org.wa_token}"},
            json={
                "messaging_product": "whatsapp",
                "to": phone.lstrip("+"),
                "type": "document",
                "document": {
                    "link": url,
                    "filename": f"{(cert.certificate_no or 'certificate').replace('/', '_')}.pdf",
                    "caption": body,
                },
            },
            timeout=30,
        )
        resp.raise_for_status()
