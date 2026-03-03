"""
轻量 HTTP Cookie 输入端点

提供一个简单的 Web 页面用于手动粘贴 Cookie，
替代阻塞式的 input() 调用。作为自动化方案的人工兜底。
"""

import asyncio
import os

from loguru import logger

try:
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

COOKIE_SERVER_PORT = int(os.getenv("COOKIE_SERVER_PORT", "8765"))
COOKIE_SERVER_ENABLED = os.getenv("COOKIE_SERVER_ENABLED", "true").lower() == "true"

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>XianyuAutoAgent - Cookie 更新</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #f5f5f5; color: #333;
    display: flex; justify-content: center; align-items: center;
    min-height: 100vh; padding: 20px;
  }
  .container {
    background: white; border-radius: 12px; padding: 32px;
    max-width: 600px; width: 100%;
    box-shadow: 0 2px 12px rgba(0,0,0,0.1);
  }
  h1 { font-size: 20px; margin-bottom: 8px; }
  .subtitle { color: #666; font-size: 14px; margin-bottom: 24px; }
  textarea {
    width: 100%; height: 150px; padding: 12px;
    border: 2px solid #e0e0e0; border-radius: 8px;
    font-family: monospace; font-size: 13px;
    resize: vertical; transition: border-color 0.2s;
  }
  textarea:focus { outline: none; border-color: #ff6600; }
  button {
    width: 100%; padding: 12px; margin-top: 16px;
    background: #ff6600; color: white; border: none;
    border-radius: 8px; font-size: 16px; cursor: pointer;
    transition: background 0.2s;
  }
  button:hover { background: #e55b00; }
  button:disabled { background: #ccc; cursor: not-allowed; }
  .status {
    margin-top: 16px; padding: 12px; border-radius: 8px;
    font-size: 14px; display: none;
  }
  .status.success { display: block; background: #e8f5e9; color: #2e7d32; }
  .status.error { display: block; background: #fbe9e7; color: #c62828; }
  .instructions {
    margin-top: 20px; padding: 16px; background: #fff3e0;
    border-radius: 8px; font-size: 13px; color: #e65100;
  }
  .instructions ol { padding-left: 20px; }
  .instructions li { margin-bottom: 4px; }
</style>
</head>
<body>
<div class="container">
  <h1>XianyuAutoAgent Cookie 更新</h1>
  <p class="subtitle">当风控触发且自动恢复失败时，请在此粘贴新的 Cookie</p>
  <textarea id="cookie" placeholder="粘贴完整的 Cookie 字符串..."></textarea>
  <button id="submit" onclick="submitCookie()">更新 Cookie</button>
  <div id="status" class="status"></div>
  <div class="instructions">
    <strong>获取 Cookie 步骤:</strong>
    <ol>
      <li>在浏览器中打开 <a href="https://www.goofish.com" target="_blank">闲鱼网页版</a></li>
      <li>完成滑块验证（如果有）</li>
      <li>按 F12 打开开发者工具 &rarr; Application &rarr; Cookies</li>
      <li>复制所有 Cookie 或使用插件导出</li>
    </ol>
  </div>
</div>
<script>
async function submitCookie() {
  const cookie = document.getElementById('cookie').value.trim();
  const status = document.getElementById('status');
  const btn = document.getElementById('submit');
  if (!cookie) {
    status.className = 'status error';
    status.textContent = 'Cookie 不能为空';
    return;
  }
  btn.disabled = true;
  btn.textContent = '提交中...';
  try {
    const resp = await fetch('/update-cookie', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cookie: cookie})
    });
    const data = await resp.json();
    if (data.success) {
      status.className = 'status success';
      status.textContent = 'Cookie 更新成功! 程序将自动恢复连接。';
      document.getElementById('cookie').value = '';
    } else {
      status.className = 'status error';
      status.textContent = 'Cookie 更新失败: ' + (data.error || '未知错误');
    }
  } catch (e) {
    status.className = 'status error';
    status.textContent = '请求失败: ' + e.message;
  }
  btn.disabled = false;
  btn.textContent = '更新 Cookie';
}
</script>
</body>
</html>"""


class CookieServer:
    """异步 HTTP Cookie 输入服务器"""

    def __init__(self, port=None):
        self.port = port or COOKIE_SERVER_PORT
        self.cookie_event = asyncio.Event()
        self.new_cookie = None
        self._runner = None

    async def start(self):
        """启动 HTTP 服务器"""
        if not AIOHTTP_AVAILABLE:
            logger.warning("aiohttp 未安装，Cookie 服务器不可用。请运行: pip install aiohttp")
            return

        app = web.Application()
        app.router.add_get('/', self._handle_index)
        app.router.add_post('/update-cookie', self._handle_update_cookie)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, '0.0.0.0', self.port)
        await site.start()
        logger.info(f"Cookie 输入服务器已启动: http://localhost:{self.port}")

    async def stop(self):
        """停止 HTTP 服务器"""
        if self._runner:
            await self._runner.cleanup()
            logger.info("Cookie 输入服务器已停止")

    async def wait_for_cookie(self, timeout=None):
        """
        等待用户通过 Web 页面提交新 Cookie。

        Args:
            timeout: 超时时间（秒），None 表示无限等待

        Returns:
            str: 新的 cookie 字符串，超时返回 None
        """
        self.cookie_event.clear()
        self.new_cookie = None
        try:
            await asyncio.wait_for(self.cookie_event.wait(), timeout=timeout)
            return self.new_cookie
        except asyncio.TimeoutError:
            return None

    async def _handle_index(self, request):
        return web.Response(text=HTML_PAGE, content_type='text/html')

    async def _handle_update_cookie(self, request):
        try:
            data = await request.json()
            cookie_str = data.get('cookie', '').strip()

            if not cookie_str:
                return web.json_response({'success': False, 'error': 'Cookie 为空'})

            # 简单验证 cookie 格式
            if '=' not in cookie_str:
                return web.json_response({'success': False, 'error': 'Cookie 格式无效'})

            self.new_cookie = cookie_str
            self.cookie_event.set()

            logger.info("通过 Web 端点收到新 Cookie")
            return web.json_response({'success': True})

        except Exception as e:
            logger.error(f"处理 Cookie 更新请求出错: {e}")
            return web.json_response({'success': False, 'error': str(e)})
