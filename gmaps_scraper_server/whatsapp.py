"""WhatsApp outreach message builder."""
from __future__ import annotations

import re
import unicodedata
from typing import Optional
from urllib.parse import quote


# Explicit code points so emojis survive any source-file encoding issues
EMOJI_WAVE = "\U0001F44B"       # 👋
EMOJI_PAW = "\U0001F43E"        # 🐾
EMOJI_GIFT = "\U0001F381"       # 🎁


def normalize_phone_for_whatsapp(phone: Optional[str]) -> Optional[str]:
    """Return digits only with Saudi country code for wa.me links."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return None
    if digits.startswith("966"):
        return digits
    if digits.startswith("0"):
        return "966" + digits[1:]
    if len(digits) == 9 and digits[0] == "5":
        return "966" + digits
    if len(digits) >= 10:
        return digits
    return "966" + digits


def clean_store_name(name: Optional[str]) -> str:
    """Remove invisible bidi/format chars scraped from Google Maps."""
    if not name:
        return "صديقي"
    # Strip Unicode format controls (RTL marks, zero-width, etc.)
    cleaned = "".join(
        ch for ch in name
        if unicodedata.category(ch) not in ("Cf", "Cc") or ch in "\n\t"
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "صديقي"


def build_waleef_message(store_name: str) -> str:
    name = clean_store_name(store_name)
    return (
        f"مرحبًا {EMOJI_WAVE} {name}\n"
        f"سؤال سريع...\n"
        f"إذا جاءك اليوم 100 عميل جديد يبحثون عن منتجات أو خدمات الحيوانات الأليفة، هل ترفضهم؟\n"
        f"هذا بالضبط ما يقدمه وليف.\n"
        f"وليف منصة متخصصة بالحيوانات الأليفة، تجمع أصحاب الحيوانات الذين يبحثون يوميًا عن: "
        f"{EMOJI_PAW} المنتجات {EMOJI_PAW} العيادات البيطرية {EMOJI_PAW} الخدمات {EMOJI_PAW} التبني والتزاوج\n"
        f"بدل أن يبحث العميل عنك... أنت تظهر أمامه عندما يكون مستعدًا للشراء.\n"
        f"{EMOJI_GIFT} اشترك الآن واحصل على شهر مجاني بالكامل. ثم 18 ريال فقط شهريًا أو 187 ريال سنويًا.\n"
        f"شاهد كيف سيظهر متجرك أو عيادتك داخل وليف: https://waleef.online/ar?join"
    )


def whatsapp_link_parts(phone: Optional[str], store_name: str) -> Optional[dict]:
    """Return phone + message for client-side URL building (best emoji support)."""
    normalized = normalize_phone_for_whatsapp(phone)
    if not normalized:
        return None
    message = build_waleef_message(store_name)
    return {"phone": normalized, "message": message}


def whatsapp_url(phone: Optional[str], store_name: str) -> Optional[str]:
    """Web WhatsApp fallback."""
    parts = whatsapp_link_parts(phone, store_name)
    if not parts:
        return None
    text = quote(parts["message"], safe="", encoding="utf-8")
    return f"https://api.whatsapp.com/send?phone={parts['phone']}&text={text}"


def whatsapp_desktop_url(phone: Optional[str], store_name: str) -> Optional[str]:
    """Opens WhatsApp desktop/mobile app directly (whatsapp:// on Mac)."""
    parts = whatsapp_link_parts(phone, store_name)
    if not parts:
        return None
    text = quote(parts["message"], safe="", encoding="utf-8")
    return f"whatsapp://send?phone={parts['phone']}&text={text}"
