"""
Notification service — Telegram and WhatsApp (Wasender API).
"""
import asyncio
from typing import Optional

import httpx

from src.core.logging_config import get_logger

logger = get_logger()

WASENDER_BASE_URL = "https://www.wasenderapi.com"


def _load_config() -> dict:
    """Load config.json lazily to avoid circular imports."""
    from src.api.routes.config import load_config
    return load_config()


async def send_telegram(message: str, config: Optional[dict] = None) -> bool:
    """Send a Telegram message. Returns True on success."""
    cfg = config or _load_config()
    telegram = cfg.get("telegram", {})

    if not telegram.get("enabled"):
        return False

    bot_token = telegram.get("bot_token", "")
    chat_id = telegram.get("chat_id", "")

    if not bot_token or not chat_id or ":" not in bot_token:
        logger.warning("Telegram not configured correctly")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    for attempt in range(3):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=10.0)
                if resp.status_code == 200:
                    return True
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 5))
                    await asyncio.sleep(retry_after)
                else:
                    logger.error(f"Telegram API error {resp.status_code}: {resp.text[:200]}")
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
        except httpx.TimeoutException:
            logger.warning(f"Telegram timeout (attempt {attempt + 1})")
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)

    return False


async def send_whatsapp(message: str, config: Optional[dict] = None) -> bool:
    """Send a WhatsApp message via Wasender API. Returns True on success."""
    cfg = config or _load_config()
    whatsapp = cfg.get("whatsapp", {})

    if not whatsapp.get("enabled"):
        return False

    api_key = whatsapp.get("api_key", "")
    recipient = whatsapp.get("recipient", "")

    if not api_key or not recipient:
        return False

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"to": recipient, "text": message}

    for attempt in range(3):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{WASENDER_BASE_URL}/api/send-message",
                    headers=headers,
                    json=payload,
                    timeout=30.0,
                )
                if resp.status_code == 200:
                    return True
                if resp.status_code == 401:
                    logger.error("WhatsApp: unauthorized — check API key")
                    return False
                if resp.status_code == 429:
                    await asyncio.sleep(int(resp.headers.get("Retry-After", 5)))
                else:
                    logger.error(f"WhatsApp API error {resp.status_code}: {resp.text[:200]}")
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
        except httpx.TimeoutException:
            logger.warning(f"WhatsApp timeout (attempt {attempt + 1})")
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
        except Exception as e:
            logger.error(f"WhatsApp send error: {e}")
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)

    return False


async def notify_trade_entry(
    symbol: str,
    qty: int,
    entry_price: float,
    sl_price: float,
    tp_price: float,
    is_paper: bool = False,
    scan_name: str = "",
    config: Optional[dict] = None,
) -> None:
    """Send entry notification (live trades only)."""
    if is_paper:
        return

    mode = "📄 PAPER" if is_paper else "🔴 LIVE"
    msg = (
        f"*{mode} ENTRY: {symbol}*\n"
        f"Price: ₹{entry_price:.2f} | Qty: {qty}\n"
        f"SL: ₹{sl_price:.2f} | TP: ₹{tp_price:.2f}\n"
        f"Scan: {scan_name}"
    )
    cfg = config or _load_config()
    await asyncio.gather(
        send_telegram(msg, cfg),
        send_whatsapp(msg, cfg),
        return_exceptions=True,
    )


async def notify_trade_exit(
    symbol: str,
    qty: int,
    entry_price: float,
    exit_price: float,
    pnl: float,
    reason: str = "MANUAL",
    is_paper: bool = False,
    config: Optional[dict] = None,
) -> None:
    """Send exit notification (live trades only)."""
    if is_paper:
        return

    emoji = "✅" if pnl >= 0 else "❌"
    mode = "📄 PAPER" if is_paper else "🔴 LIVE"
    msg = (
        f"*{mode} EXIT: {symbol}* {emoji}\n"
        f"Entry: ₹{entry_price:.2f} → Exit: ₹{exit_price:.2f}\n"
        f"P&L: ₹{pnl:+.2f} | Qty: {qty}\n"
        f"Reason: {reason}"
    )
    cfg = config or _load_config()
    await asyncio.gather(
        send_telegram(msg, cfg),
        send_whatsapp(msg, cfg),
        return_exceptions=True,
    )
