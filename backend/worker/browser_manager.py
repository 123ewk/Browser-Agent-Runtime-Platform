"""BrowserManager —— Playwright 浏览器生命周期管理

设计要点:
- 管理 Playwright 实例 + Browser + BrowserContext 的生命周期
- launch_persistent_context 用于持久化浏览器会话(登录态)
- V1 只启动 Chromium,headless 模式
- 提供 screenshot() 方法返回 bytes
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright


class BrowserManager:
    """Playwright 浏览器生命周期管理器

    用法:
        manager = BrowserManager()
        await manager.start()
        page = manager.page
        screenshot_bytes = await manager.screenshot()
        await manager.stop()
    """

    def __init__(
        self,
        headless: bool = True,
        user_data_dir: str | None = None,
    ) -> None:
        self._headless = headless
        self._user_data_dir = user_data_dir

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def page(self) -> Page:
        """获取当前 Page 对象"""
        if self._page is None:
            raise RuntimeError("BrowserManager 未启动,请先调用 start()")
        return self._page

    async def start(self, storage_state_path: str | None = None) -> None:
        """启动 Playwright + Chromium + 创建 BrowserContext

        默认使用 headless 模式。
        如果提供了 storage_state_path,则加载已有的浏览器状态(登录态)。
        """
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()

        # 使用 launch_persistent_context 以获得持久化用户数据
        user_dir = self._user_data_dir or str(Path.cwd() / "data" / "browser_profile")
        Path(user_dir).mkdir(parents=True, exist_ok=True)

        self._context = await self._playwright.chromium.launch_persistent_context(
            user_dir,
            headless=self._headless,
            # V1 固定视口,方便截图一致性
            viewport={"width": 1280, "height": 720},
            # 中文语言环境
            locale="zh-CN",
        )

        if storage_state_path and Path(storage_state_path).exists():
            # Playwright 类型标注对 list[dict] 兼容性差,实际运行时接受这种结构
            await self._context.add_cookies(self._load_storage_state(storage_state_path))  # type: ignore[arg-type]

        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = await self._context.new_page()

    async def navigate(self, url: str, timeout: float = 30_000) -> None:
        """导航到指定 URL"""
        await self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)

    async def screenshot(self) -> bytes:
        """截取当前页面完整截图,返回 PNG bytes"""
        return await self.page.screenshot(full_page=False, type="png")

    async def click(self, selector: str, timeout: float = 10_000) -> None:
        """点击指定元素"""
        await self.page.click(selector, timeout=timeout)

    async def input_text(self, selector: str, text: str, timeout: float = 10_000) -> None:
        """在输入框中输入文字"""
        await self.page.fill(selector, text, timeout=timeout)

    async def get_text(self, selector: str) -> str:
        """获取元素文本内容"""
        return await self.page.text_content(selector) or ""

    async def get_title(self) -> str:
        """获取页面标题"""
        return await self.page.title()

    async def get_url(self) -> str:
        """获取当前 URL"""
        return self.page.url

    async def stop(self) -> None:
        """关闭浏览器并清理资源"""
        if self._context is not None:
            await self._context.close()
            self._context = None
            self._page = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    @staticmethod
    def _load_storage_state(path: str) -> list[dict]:
        """从文件加载 cookies(简化版,不完整实现 storage_state)"""
        import json

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("cookies", [])
        except Exception:
            import structlog

            structlog.get_logger(__name__).warning(
                "browser_manager.load_storage_state_failed",
                path=path,
            )
            return []
