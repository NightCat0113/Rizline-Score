"""Paginated collection views for /collection."""

from __future__ import annotations

import asyncio
import io
import logging
import threading
from pathlib import Path

import discord

from bot.ui.collection_image import render_bio_sheet, render_collection_grid


logger = logging.getLogger("rizline.bot")


_BIO_COPY = {
    "en": ("Bios", "Owned", "Page", "No bios match this filter.", "Part 1", "Part 2", "Catalog"),
    "zh-Hans": ("称号", "已获得", "页", "没有符合条件的称号。", "前半", "后半", "图鉴"),
    "zh-Hant": ("稱號", "已獲得", "頁", "沒有符合條件的稱號。", "前半", "後半", "圖鑑"),
    "ja": ("称号", "所持", "ページ", "該当する称号はありません。", "前半", "後半", "図鑑"),
}

_GRID_COPY = {
    "en": {
        "layout": "Layouts",
        "illustration": "Arts",
        "owned": "Owned",
        "page": "Page",
        "all": "All",
        "owned_filter": "Owned",
        "missing": "Missing",
        "catalog": "Catalog",
        "items": "Items",
    },
    "zh-Hans": {
        "layout": "布局",
        "illustration": "插画",
        "owned": "已获得",
        "page": "页",
        "all": "全部",
        "owned_filter": "已获得",
        "missing": "未获得",
        "catalog": "图鉴",
        "items": "条目",
    },
    "zh-Hant": {
        "layout": "佈局",
        "illustration": "插畫",
        "owned": "已獲得",
        "page": "頁",
        "all": "全部",
        "owned_filter": "已獲得",
        "missing": "未獲得",
        "catalog": "圖鑑",
        "items": "項目",
    },
    "ja": {
        "layout": "レイアウト",
        "illustration": "イラスト",
        "owned": "所持",
        "page": "ページ",
        "all": "すべて",
        "owned_filter": "所持",
        "missing": "未所持",
        "catalog": "図鑑",
        "items": "件数",
    },
}

_BUTTONS = {
    "en": ("Previous", "Next"),
    "zh-Hans": ("上一页", "下一页"),
    "zh-Hant": ("上一頁", "下一頁"),
    "ja": ("前へ", "次へ"),
}


def _language(language: str, table: dict) -> str:
    return language if language in table else "en"


class CollectionBioView(discord.ui.View):
    def __init__(
        self,
        *,
        owner_id: int,
        rows: list[dict[str, str]],
        owned: set[str] | None,
        owned_count: int,
        total: int,
        language: str,
        font_path: Path,
        page_size: int = 10,
    ) -> None:
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.rows = rows
        self.owned = owned
        self.owned_count = owned_count
        self.total = total
        self.language = _language(language, _BIO_COPY)
        self.font_path = font_path
        self.page_size = page_size
        self.page = 0
        previous, nxt = _BUTTONS[self.language]
        self.previous_button.label = previous
        self.next_button.label = nxt
        self._update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who opened this list can use these buttons.",
                ephemeral=True,
            )
            return False
        return True

    def caption(self) -> str:
        title, owned_label, page_label, _empty, _part1, _part2, catalog = _BIO_COPY[self.language]
        pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        if self.owned is None:
            return f"**{title}** | {catalog} {self.total} | {page_label} {self.page + 1}/{pages}"
        return f"**{title}** | {owned_label} {self.owned_count} / {self.total} | {page_label} {self.page + 1}/{pages}"

    def render_png(self) -> bytes:
        title, owned_label, page_label, _empty, part1, part2, catalog = _BIO_COPY[self.language]
        pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        current = self.rows[self.page * self.page_size : (self.page + 1) * self.page_size]
        if self.owned is None:
            progress = f"{catalog} {self.total}"
        else:
            progress = f"{owned_label} {self.owned_count} / {self.total}"
        return render_bio_sheet(
            rows=current,
            owned=self.owned,
            title=title,
            part1=part1,
            part2=part2,
            progress=progress,
            page_label=f"{page_label} {self.page + 1}/{pages}",
            font_path=self.font_path,
        )

    def _update_buttons(self) -> None:
        pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        self.previous_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= pages - 1

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.page = max(0, self.page - 1)
        await self._show(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        self.page = min(pages - 1, self.page + 1)
        await self._show(interaction)

    async def _show(self, interaction: discord.Interaction) -> None:
        self._update_buttons()
        await interaction.response.defer()
        png = await asyncio.to_thread(self.render_png)
        attachment = discord.File(io.BytesIO(png), filename="collection.png")
        await interaction.edit_original_response(content=self.caption(), attachments=[attachment], view=self)


class CollectionGridView(discord.ui.View):
    def __init__(
        self,
        *,
        owner_id: int,
        rows: list[dict[str, str]],
        owned: set[str] | None,
        owned_count: int,
        total: int,
        kind: str,
        status: str,
        language: str,
        illust_hires_dir: Path,
        illust_dir: Path,
        font_path: Path,
        repo_root: Path,
        page_size: int = 12,
        title: str | None = None,
    ) -> None:
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.rows = rows
        self.owned = owned
        self.owned_count = owned_count
        self.total = total
        self.kind = kind if kind in {"layout", "illustration"} else "illustration"
        self.status = status if status in {"all", "owned", "missing"} else "all"
        self.language = _language(language, _GRID_COPY)
        self.illust_hires_dir = illust_hires_dir
        self.illust_dir = illust_dir
        self.font_path = font_path
        self.repo_root = repo_root
        self.page_size = page_size
        self.title = title
        self.page = 0
        self._pages: dict[int, bytes] = {}
        self._page_locks: dict[int, threading.Lock] = {}
        self._guard = threading.Lock()
        self._order: list[int] = []
        self._queued: set[int] = set()
        self._failed: set[int] = set()
        self._wake = threading.Event()
        self._closed = False
        self._worker = threading.Thread(target=self._build_pages, name="collection-pages", daemon=True)
        self._worker.start()
        previous, nxt = _BUTTONS[self.language]
        self.previous_button.label = previous
        self.next_button.label = nxt
        self._update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who opened this list can use these buttons.",
                ephemeral=True,
            )
            return False
        return True

    def caption(self) -> str:
        copy = _GRID_COPY[self.language]
        pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        heading = self.title or copy[self.kind]
        if self.owned is None:
            return f"**{heading}** | {copy['catalog']} {self.total} | {copy['page']} {self.page + 1}/{pages}"
        return (
            f"**{heading}** | {copy['owned']} {self.owned_count} / {self.total}"
            f" | {copy[self._status_key()]} | {copy['page']} {self.page + 1}/{pages}"
        )

    def render_png(self) -> bytes:
        return self._render_page(self.page)

    def _render_page(self, page: int) -> bytes:
        cached = self._pages.get(page)
        if cached is not None:
            return cached
        with self._lock_for(page):
            cached = self._pages.get(page)
            if cached is not None:
                return cached
            copy = _GRID_COPY[self.language]
            pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
            current = self.rows[page * self.page_size : (page + 1) * self.page_size]
            heading = self.title or copy[self.kind]
            if self.owned is None:
                progress = f"{copy['catalog']} {self.total}"
            else:
                progress = f"{copy['owned']} {self.owned_count} / {self.total}"
            png = render_collection_grid(
                rows=current,
                owned=self.owned,
                title=heading,
                progress=progress,
                page_label=f"{copy['page']} {page + 1}/{pages}",
                illust_hires_dir=self.illust_hires_dir,
                illust_dir=self.illust_dir,
                font_path=self.font_path,
                repo_root=self.repo_root,
            )
            self._pages[page] = png
            return png

    def _lock_for(self, page: int) -> threading.Lock:
        with self._guard:
            lock = self._page_locks.get(page)
            if lock is None:
                lock = threading.Lock()
                self._page_locks[page] = lock
            return lock

    def prewarm_soon(self) -> None:
        pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        for page in range(pages):
            self._enqueue(page)

    def _enqueue(self, page: int, *, front: bool = False) -> None:
        with self._guard:
            if page in self._pages or page in self._failed:
                return
            if page in self._queued:
                if front and page in self._order:
                    self._order.remove(page)
                    self._order.insert(0, page)
                return
            self._queued.add(page)
            if front:
                self._order.insert(0, page)
            else:
                self._order.append(page)
        self._wake.set()

    def _build_pages(self) -> None:
        while not self._closed:
            with self._guard:
                page = self._order.pop(0) if self._order else None
            if page is None:
                self._wake.wait(0.2)
                self._wake.clear()
                continue
            try:
                self._render_page(page)
            except Exception as exc:
                logger.error("collection page failed type=%s", exc.__class__.__name__)
                with self._guard:
                    self._failed.add(page)
            finally:
                with self._guard:
                    self._queued.discard(page)
                self._wake.set()

    def _wait_page(self, page: int) -> bytes:
        self._enqueue(page, front=True)
        while True:
            cached = self._pages.get(page)
            if cached is not None:
                return cached
            with self._guard:
                failed = page in self._failed
            if failed:
                raise RuntimeError("collection page failed")
            self._wake.wait(0.2)
            self._wake.clear()

    async def _show(self, interaction: discord.Interaction) -> None:
        self._update_buttons()
        cached = self._pages.get(self.page)
        if cached is not None:
            attachment = discord.File(io.BytesIO(cached), filename="collection.png")
            await interaction.response.edit_message(content=self.caption(), attachments=[attachment], view=self)
            self.prewarm_soon()
            return
        await interaction.response.defer()
        try:
            png = await asyncio.to_thread(self._wait_page, self.page)
        except Exception as exc:
            logger.error("collection page failed type=%s", exc.__class__.__name__)
            await interaction.followup.send(
                "Something went wrong. The details were not included here.",
                ephemeral=True,
            )
            return
        attachment = discord.File(io.BytesIO(png), filename="collection.png")
        await interaction.edit_original_response(content=self.caption(), attachments=[attachment], view=self)
        self.prewarm_soon()

    async def on_timeout(self) -> None:
        self._closed = True
        self._wake.set()

    def _status_key(self) -> str:
        return {"owned": "owned_filter", "missing": "missing"}.get(self.status, "all")

    def _update_buttons(self) -> None:
        pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        self.previous_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= pages - 1

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.page = max(0, self.page - 1)
        await self._show(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        self.page = min(pages - 1, self.page + 1)
        await self._show(interaction)


def _bio_line(row: dict[str, str], owned: set[str]) -> str:
    stem = row.get("id") or ""
    left = f"bio.{stem}.1" in owned
    right = f"bio.{stem}.2" in owned
    if not left and not right and (stem in owned or f"bio.{stem}" in owned):
        left = right = True
    left_cell = f"{'✓' if left else '☐'} {_bio_cell(row.get('title1') or '—')}"
    right_cell = f"{'✓' if right else '☐'} {_bio_cell(row.get('title2') or '—')}"
    return f"| {left_cell} | {right_cell} |"


def _bio_cell(text: str) -> str:
    cleaned = " ".join(text.replace("|", "/").split())
    return cleaned or "—"
