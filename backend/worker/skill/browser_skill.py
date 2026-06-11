"""BrowserSkill —— V1 唯一技能: 浏览器自动化

设计约束 (硬):
- 纯确定性执行器: 接收 ActionDetail → 执行 → 返回 SkillResult
- 禁止: retry, fallback, DOM 判断, 元素猜测, 条件分支
- 封装 BrowserManager, 按 action.type 分发到对应方法
"""

from __future__ import annotations

from app.runtime.protocol.schemas import ActionDetail
from worker.browser_manager import BrowserManager
from worker.skill.base import BaseSkill, SkillResult


class BrowserSkill(BaseSkill):
    """浏览器自动化技能 —— V1 唯一实现

    capabilities 列表定义了此技能支持的所有原子操作。
    PolicyEngine 输出的 action.type 必须匹配其中一个能力。
    """

    name = "browser"
    description = "浏览器自动化: 导航、点击、输入、截图、文本提取"
    # capabilities 必须与 execute() 中实际支持的 action.type 一一对应,
    # 否则 PolicyEngine 输出未实现的类型会落到 execute() 的 else 分支报错。
    # web.scroll / web.wait 暂未在 execute 中实现,留待 V1.1 补齐。
    capabilities = [
        "web.navigate",
        "web.click",
        "web.input_text",
        "web.screenshot",
        "web.extract",
    ]

    def __init__(self, browser: BrowserManager) -> None:
        self._browser = browser

    async def execute(self, action: ActionDetail) -> SkillResult:
        """执行单一浏览器操作

        纯分发 —— 不做 retry,不做 fallback,不做 DOM 判断。
        失败直接返回 error,由 Worker 上报 Runtime。

        V2.5: navigate/click/input_text 类动作后自动提取 dom_summary + visible_text
        (给 ReActEngine 提供页面上下文)。
        """
        try:
            if action.type == "navigate":
                await self._browser.navigate(action.target or "")
                url = await self._browser.get_url()
                title = await self._browser.get_title()
                dom, visible = await self._extract_page_state()
                return SkillResult(
                    status="ok",
                    summary=f"已导航到: {title}",
                    url=url,
                    title=title,
                    dom_summary=dom,
                    visible_text=visible,
                )

            elif action.type == "click":
                await self._browser.click(action.target or "")
                url = await self._browser.get_url()
                title = await self._browser.get_title()
                dom, visible = await self._extract_page_state()
                return SkillResult(
                    status="ok",
                    summary=f"已点击: {action.target}",
                    url=url,
                    title=title,
                    dom_summary=dom,
                    visible_text=visible,
                )

            elif action.type == "input_text":
                await self._browser.input_text(action.target or "", action.value or "")
                url = await self._browser.get_url()
                title = await self._browser.get_title()
                dom, visible = await self._extract_page_state()
                return SkillResult(
                    status="ok",
                    summary=f"已在 {action.target} 输入: {action.value}",
                    url=url,
                    title=title,
                    dom_summary=dom,
                    visible_text=visible,
                )

            elif action.type == "screenshot":
                data = await self._browser.screenshot()
                # 保存截图到本地
                from pathlib import Path
                from uuid import uuid4

                screenshot_key = f"screenshots/{uuid4().hex[:12]}.png"
                path = Path.cwd() / "data" / screenshot_key
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)

                url = await self._browser.get_url()
                title = await self._browser.get_title()
                dom, visible = await self._extract_page_state()
                return SkillResult(
                    status="ok",
                    summary="截图已保存",
                    url=url,
                    title=title,
                    screenshot_key=screenshot_key,
                    dom_summary=dom,
                    visible_text=visible,
                )

            elif action.type == "extract":
                text = await self._browser.get_text(action.target or "body")
                url = await self._browser.get_url()
                title = await self._browser.get_title()
                dom, visible = await self._extract_page_state()
                return SkillResult(
                    status="ok",
                    summary=f"已提取文本 ({len(text)} 字符)",
                    url=url,
                    title=title,
                    dom_summary=dom,
                    visible_text=visible,
                )

            else:
                return SkillResult(
                    status="error",
                    summary=f"不支持的操作类型: {action.type}",
                    error=f"unknown_action_type: {action.type}",
                )

        except Exception as e:
            return SkillResult(
                status="error",
                summary=f"执行失败: {e}",
                error=str(e),
            )

    async def _extract_page_state(self) -> tuple[str, str]:
        """V2.5: 提取当前页面的 dom_summary 和 visible_text

        dom_summary: 结构化提取可交互元素 (按钮/输入框/链接 + 关键属性, ≤3000 字符)
        visible_text: 页面实际可见的纯文本 (≤2000 字符)
        两者互补, 给 ReActEngine 提供页面上下文。
        """
        dom = ""
        visible = ""
        page = self._browser.page  # BrowserManager.page 属性 (raise if None)

        try:
            # 提取可见文本
            visible = await page.inner_text("body") or ""
            visible = visible[:2000]
        except Exception:
            pass

        try:
            # 提取可交互元素结构化摘要
            js_code = """
            () => {
                const elements = Array.from(document.querySelectorAll(
                    'button, input, a, [role="button"], [role="link"], h1, h2, h3, [aria-label]'
                ));
                const summary = elements.slice(0, 100).map(el => {
                    const tag = el.tagName.toLowerCase();
                    const text = (el.innerText || el.value || el.ariaLabel || '').slice(0, 100);
                    const attrs = [];
                    if (el.id) attrs.push('id=' + el.id);
                    if (el.name) attrs.push('name=' + el.name);
                    if (el.type) attrs.push('type=' + el.type);
                    if (el.href) attrs.push('href=' + el.href.slice(0, 50));
                    return '<' + tag + (attrs.length ? ' ' + attrs.join(' ') : '') + '>' + text + '</' + tag + '>';
                }).join('\\n');
                return summary.slice(0, 3000);
            }
            """
            dom = await page.evaluate(js_code) or ""
            dom = dom[:3000]
        except Exception:
            pass

        return dom, visible
