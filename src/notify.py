"""统一通知模块：飞书（默认）/ Telegram，支持 provider 切换与凭证缺失自动降级。

用法：
    from notify import notify
    notify(message, provider="feishu")

provider 取值：feishu（默认）| telegram | both
凭证（优先环境变量，适配 GitHub Secrets）：
    FEISHU_WEBHOOK_URL  飞书自定义机器人 webhook 地址（必需）
    FEISHU_SECRET       飞书机器人加签密钥（可选，创建机器人时若勾选"签名校验"则必填）
    TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID（可选）
"""
import base64
import hashlib
import hmac
import html
import logging
import os
import re
import time

import requests

logger = logging.getLogger("QX-Notify")

FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL", "")
FEISHU_SECRET = os.environ.get("FEISHU_SECRET", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# 文案固定前缀：兼容飞书机器人"自定义关键词"安全策略（关键词建议设为 QX 或 配置）
KEYWORD_PREFIX = "【QX配置】"


def html_to_text(message):
    """Telegram HTML 报告 → 纯文本（飞书 text 消息不支持 HTML）"""
    text = re.sub(r'<a href="(.*?)">(.*?)</a>', r"\2: \1", message)
    text = re.sub(r"<b>(.*?)</b>", r"\1", text)
    text = re.sub(r"<code>(.*?)</code>", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def feishu_sign(secret, timestamp):
    """飞书自定义机器人签名校验算法（官方：key=timestamp\\nsecret，HMAC-SHA256 后 base64）"""
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


def send_feishu(message, webhook_url=None, secret=None):
    webhook_url = webhook_url or FEISHU_WEBHOOK_URL
    if not webhook_url:
        logger.warning("⚠️ [Notify] 未配置 FEISHU_WEBHOOK_URL，跳过飞书通知")
        return False

    payload = {"msg_type": "text", "content": {"text": f"{KEYWORD_PREFIX}\n{html_to_text(message)}"}}
    secret = secret if secret is not None else FEISHU_SECRET
    if secret:
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = feishu_sign(secret, timestamp)

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        # 飞书成功返回 {"code":0}；签名错误/关键词不匹配等会返回非 0 code
        if data.get("code", 0) != 0:
            logger.error(f"❌ [Notify] 飞书返回错误: {data}")
            return False
        logger.info("📤 [Notify] 飞书通知发送成功")
        return True
    except Exception as e:
        logger.error(f"❌ [Notify] 飞书通知发送失败: {e}")
        return False


def send_telegram(message, bot_token=None, chat_id=None):
    bot_token = bot_token or TELEGRAM_BOT_TOKEN
    chat_id = chat_id or TELEGRAM_CHAT_ID
    if not bot_token or not chat_id or bot_token == "xxx":
        logger.warning("⚠️ [Notify] 未配置 Telegram，跳过通知")
        return False

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("📤 [Notify] Telegram 通知发送成功")
        return True
    except Exception as e:
        logger.error(f"❌ [Notify] Telegram 通知发送失败: {e}")
        return False


def notify(message, provider="feishu"):
    """按 provider 发送通知；首选通道凭证缺失或发送失败时，自动降级到另一通道"""
    provider = (provider or "feishu").strip().lower()
    if provider not in ("feishu", "telegram", "both"):
        logger.warning(f"⚠️ [Notify] 未知 provider: {provider}，回退 feishu")
        provider = "feishu"

    if provider == "feishu":
        return send_feishu(message) or send_telegram(message)
    if provider == "telegram":
        return send_telegram(message) or send_feishu(message)
    # both：双通道都发，任一成功即视为成功
    return send_feishu(message) | send_telegram(message)
