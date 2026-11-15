"""Links that open the pharmacist's own WhatsApp or email app with the approved message ready to send.

The app never sends anything itself: the pharmacist still presses Send in WhatsApp or their mail program.
"""
import re
from urllib.parse import quote

_EMAIL = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


def phone_digits(contact: str):
    """International number for wa.me (digits only), or None if the contact isn't a phone number."""
    if not contact or _EMAIL.match(contact.strip()):
        return None
    digits = re.sub(r"\D", "", contact)
    if contact.strip().startswith("00"):
        digits = digits[2:]
    return digits if 8 <= len(digits) <= 15 else None


def whatsapp_url(contact: str, text: str) -> str:
    """With a phone number, opens that chat; otherwise WhatsApp asks which contact to send to."""
    digits = phone_digits(contact)
    return f"https://wa.me/{digits}?text={quote(text)}" if digits else f"https://wa.me/?text={quote(text)}"


def email_url(contact: str, subject: str, body: str) -> str:
    to = contact.strip() if contact and _EMAIL.match(contact.strip()) else ""
    return f"mailto:{quote(to, safe='@')}?subject={quote(subject)}&body={quote(body)}"
