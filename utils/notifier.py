"""
多渠道通知系统

支持:
- Webhook（通用，支持飞书/钉钉/Slack/Discord）
- Bark（iOS 推送）
- Server 酱（微信推送）
"""

import os
import asyncio
from datetime import datetime

from loguru import logger

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


NOTIFICATION_TYPE = os.getenv("NOTIFICATION_TYPE", "none").lower()
NOTIFICATION_WEBHOOK_URL = os.getenv("NOTIFICATION_WEBHOOK_URL", "")


class Notifier:
    """多渠道通知器"""

    def __init__(self, notification_type=None, webhook_url=None):
        self.notification_type = notification_type or NOTIFICATION_TYPE
        self.webhook_url = webhook_url or NOTIFICATION_WEBHOOK_URL

        if self.notification_type != "none" and not HTTPX_AVAILABLE:
            logger.warning("httpx 未安装，通知功能不可用。请运行: pip install httpx")
            self.notification_type = "none"

        if self.notification_type != "none":
            logger.info(f"通知系统已启用: {self.notification_type}")

    def notify(self, message, title="XianyuAutoAgent"):
        """同步通知接口（从同步代码调用）"""
        if self.notification_type == "none":
            return

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.async_notify(message, title))
        except RuntimeError:
            # 没有运行中的事件循环，用新循环运行
            asyncio.run(self.async_notify(message, title))

    async def async_notify(self, message, title="XianyuAutoAgent"):
        """异步通知接口"""
        if self.notification_type == "none":
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_message = f"[{timestamp}] {message}"

        try:
            if self.notification_type == "webhook":
                await self._send_webhook(full_message, title)
            elif self.notification_type == "bark":
                await self._send_bark(full_message, title)
            elif self.notification_type == "serverchan":
                await self._send_serverchan(full_message, title)
            else:
                logger.debug(f"未知通知类型: {self.notification_type}")
        except Exception as e:
            logger.error(f"发送通知失败: {e}")

    async def _send_webhook(self, message, title):
        """发送 Webhook 通知（兼容飞书/钉钉/Slack/Discord）"""
        if not self.webhook_url:
            logger.warning("NOTIFICATION_WEBHOOK_URL 未配置")
            return

        # 自动检测 Webhook 类型
        url = self.webhook_url
        if "oapi.dingtalk.com" in url:
            payload = {
                "msgtype": "text",
                "text": {"content": f"{title}: {message}"}
            }
        elif "open.feishu.cn" in url or "open.larksuite.com" in url:
            payload = {
                "msg_type": "text",
                "content": {"text": f"{title}: {message}"}
            }
        elif "discord.com" in url:
            payload = {
                "content": f"**{title}**\n{message}"
            }
        else:
            # 通用 Slack 兼容格式
            payload = {
                "text": f"*{title}*\n{message}"
            }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code < 300:
                logger.debug("Webhook 通知发送成功")
            else:
                logger.warning(f"Webhook 通知发送失败: {resp.status_code} {resp.text}")

    async def _send_bark(self, message, title):
        """发送 Bark 通知（iOS）"""
        if not self.webhook_url:
            logger.warning("NOTIFICATION_WEBHOOK_URL 未配置（Bark URL）")
            return

        # Bark URL 格式: https://api.day.app/YOUR_KEY/
        url = self.webhook_url.rstrip('/')
        bark_url = f"{url}/{title}/{message}"

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(bark_url)
            if resp.status_code == 200:
                logger.debug("Bark 通知发送成功")
            else:
                logger.warning(f"Bark 通知发送失败: {resp.status_code}")

    async def _send_serverchan(self, message, title):
        """发送 Server 酱通知（微信）"""
        if not self.webhook_url:
            logger.warning("NOTIFICATION_WEBHOOK_URL 未配置（Server 酱 URL）")
            return

        # Server 酱 URL 格式: https://sctapi.ftqq.com/YOUR_KEY.send
        url = self.webhook_url
        payload = {
            "title": title,
            "desp": message
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, data=payload)
            if resp.status_code == 200:
                logger.debug("Server 酱通知发送成功")
            else:
                logger.warning(f"Server 酱通知发送失败: {resp.status_code}")


# 全局单例
_notifier = None


def get_notifier():
    """获取全局通知器实例"""
    global _notifier
    if _notifier is None:
        _notifier = Notifier()
    return _notifier
