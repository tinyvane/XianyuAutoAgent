"""
Playwright CDP 浏览器 Cookie 提取器

通过 CDP 连接到用户已登录的 Chrome 浏览器，
导航到闲鱼 IM 页面提取所有 cookie（包括 httpOnly）。
如遇 Baxia 滑块则自动调用 SliderSolver 解决。
"""

import asyncio
import os
import random

from loguru import logger


CHROME_CDP_URL = os.getenv("CHROME_CDP_URL", "http://localhost:9222")
GOOFISH_IM_URL = "https://www.goofish.com/im"
GOOFISH_DOMAIN = ".goofish.com"


class BrowserCookieExtractor:
    """通过 CDP 连接 Chrome 提取闲鱼 Cookie"""

    def __init__(self, cdp_url=None):
        self.cdp_url = cdp_url or CHROME_CDP_URL
        self._playwright = None
        self._browser = None

    async def _connect(self):
        """连接到 Chrome CDP"""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("playwright 未安装。请运行: pip install playwright && playwright install chromium")
            return False

        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.connect_over_cdp(self.cdp_url)
            logger.info(f"已连接到 Chrome CDP: {self.cdp_url}")
            return True
        except Exception as e:
            logger.error(f"无法连接到 Chrome CDP ({self.cdp_url}): {e}")
            logger.error("请确保 Chrome 以 --remote-debugging-port=9222 启动")
            await self._cleanup()
            return False

    async def _cleanup(self):
        """清理资源"""
        try:
            if self._browser:
                # 不要关闭通过 CDP 连接的浏览器，只断开连接
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
        except Exception as e:
            logger.debug(f"清理资源时出错: {e}")

    async def extract_cookies(self):
        """
        提取闲鱼 Cookie。

        流程:
        1. 连接到 Chrome CDP
        2. 打开新标签页，导航到闲鱼 IM
        3. 检测 Baxia 滑块，如有则自动解决
        4. 提取所有 cookie
        5. 返回 cookie 字符串

        Returns:
            str: cookie 字符串（格式: "name1=value1; name2=value2"），失败返回 None
        """
        if not await self._connect():
            return None

        page = None
        try:
            # 获取默认 context（已登录的会话）
            contexts = self._browser.contexts
            if not contexts:
                logger.error("Chrome 中没有可用的浏览器上下文")
                return None

            context = contexts[0]

            # 创建新标签页
            page = await context.new_page()
            logger.info(f"正在导航到 {GOOFISH_IM_URL}...")

            # 导航到闲鱼 IM 页面
            await page.goto(GOOFISH_IM_URL, wait_until="domcontentloaded",
                            timeout=30000)

            # 等待页面稳定
            await asyncio.sleep(random.uniform(2.0, 4.0))

            # 检测并解决滑块
            from utils.slider_solver import attempt_solve_slider
            slider_solved = await attempt_solve_slider(page)

            if not slider_solved:
                logger.error("滑块解决失败，无法提取 cookie")
                return None

            # 等待一下让 cookie 更新
            await asyncio.sleep(random.uniform(1.0, 2.0))

            # 提取所有 cookie（包括 httpOnly）
            cookies = await context.cookies(GOOFISH_IM_URL)

            if not cookies:
                logger.warning("未获取到任何 cookie")
                return None

            # 过滤闲鱼相关域名的 cookie
            relevant_cookies = []
            for cookie in cookies:
                domain = cookie.get('domain', '')
                if 'goofish.com' in domain or 'taobao.com' in domain or 'alibaba' in domain:
                    relevant_cookies.append(cookie)

            if not relevant_cookies:
                logger.warning("未找到闲鱼相关的 cookie")
                # 回退：使用所有 cookie
                relevant_cookies = cookies

            # 构建 cookie 字符串
            cookie_str = '; '.join(
                f"{c['name']}={c['value']}" for c in relevant_cookies
            )

            logger.success(f"成功提取 {len(relevant_cookies)} 个 cookie")
            logger.debug(f"Cookie 字符串长度: {len(cookie_str)}")

            return cookie_str

        except Exception as e:
            logger.error(f"提取 cookie 时出错: {e}")
            return None

        finally:
            # 关闭我们打开的标签页
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            await self._cleanup()

    async def is_chrome_available(self):
        """检查 Chrome CDP 是否可用"""
        try:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            try:
                browser = await pw.chromium.connect_over_cdp(self.cdp_url)
                browser = None  # 不关闭，只断开
                return True
            except Exception:
                return False
            finally:
                await pw.stop()
        except ImportError:
            return False
