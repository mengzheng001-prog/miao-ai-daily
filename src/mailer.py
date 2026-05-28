"""邮件推送：把当天日报作为 HTML 邮件发送。

配置全走环境变量（.env / GitHub Secrets）：
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_TO
未配置则跳过（本地无 SMTP 也能正常生成日报，不报错）。
端口 465 走 SSL，其它端口走 STARTTLS。
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

logger = logging.getLogger(__name__)


def _cfg() -> dict[str, str] | None:
    host = os.environ.get("SMTP_HOST", "").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    pwd = os.environ.get("SMTP_PASS", "").strip()
    to = os.environ.get("MAIL_TO", "").strip() or user
    if not (host and user and pwd and to):
        return None
    return {
        "host": host,
        "port": os.environ.get("SMTP_PORT", "465").strip() or "465",
        "user": user,
        "pwd": pwd,
        "to": to,
    }


def send_report(html: str, subject: str) -> bool:
    """发送 HTML 日报邮件。未配置 SMTP 时跳过并返回 False。"""
    cfg = _cfg()
    if cfg is None:
        logger.info("未配置 SMTP（SMTP_HOST/USER/PASS/MAIL_TO），跳过邮件推送")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("喵仔仔 AI 日报", cfg["user"]))
    msg["To"] = cfg["to"]
    msg.set_content("你的邮件客户端不支持 HTML，请用支持 HTML 的客户端查看今日 AI 日报。")
    msg.add_alternative(html, subtype="html")

    port = int(cfg["port"])
    try:
        if port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg["host"], port, context=ctx, timeout=30) as s:
                s.login(cfg["user"], cfg["pwd"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg["host"], port, timeout=30) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(cfg["user"], cfg["pwd"])
                s.send_message(msg)
        logger.info("邮件已发送给 %s", cfg["to"])
        return True
    except Exception as exc:  # 邮件失败不应影响日报已生成的事实
        logger.warning("邮件发送失败：%s", exc)
        return False
