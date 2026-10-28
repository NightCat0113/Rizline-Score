"""Private weekly-task list for /weekly."""

from __future__ import annotations

import discord

from bot.services.weekly_tasks import WeeklyBoard, status_label


_COPY = {
    "en": ("Weekly tasks", "No weekly tasks were returned.", "Page", "How to"),
    "zh-Hans": ("每周任务", "没有返回每周任务。", "页", "做法"),
    "zh-Hant": ("每週任務", "沒有返回每週任務。", "頁", "做法"),
    "ja": ("ウィークリー", "ウィークリータスクはありません。", "ページ", "やり方"),
}


class WeeklyTaskView(discord.ui.View):
    def __init__(self, *, owner_id: int, board: WeeklyBoard, language: str, page_size: int = 6) -> None:
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.board = board
        self.language = language if language in _COPY else "en"
        self.page_size = page_size
        self.page = 0
        self.previous_button.label = {"zh-Hans": "上一页", "zh-Hant": "上一頁", "ja": "前へ"}.get(self.language, "Previous")
        self.next_button.label = {"zh-Hans": "下一页", "zh-Hant": "下一頁", "ja": "次へ"}.get(self.language, "Next")
        self._update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who opened this list can use these buttons.",
                ephemeral=True,
            )
            return False
        return True

    def render(self) -> str:
        title, empty_text, page_label, how_to = _COPY[self.language]
        tasks = self.board.tasks
        pages = max(1, (len(tasks) + self.page_size - 1) // self.page_size)
        current = tasks[self.page * self.page_size : (self.page + 1) * self.page_size]
        lines = [f"**{title}**"]
        if not current:
            lines.append(empty_text)
        for task in current:
            target = f"/{task.target}" if task.target else ""
            state = status_label(task.status, self.language)
            lines.append(f"**{task.title}** — {task.progress}{target} · {state}")
            if task.desc:
                lines.append(f"{how_to}: {task.desc}")
        lines.append(f"{page_label} {self.page + 1}/{pages}")
        return "\n".join(lines)

    def _update_buttons(self) -> None:
        pages = max(1, (len(self.board.tasks) + self.page_size - 1) // self.page_size)
        self.previous_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= pages - 1

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(content=self.render(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        pages = max(1, (len(self.board.tasks) + self.page_size - 1) // self.page_size)
        self.page = min(pages - 1, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(content=self.render(), view=self)
