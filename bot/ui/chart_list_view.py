"""Paginated constant browser for /charts."""

from __future__ import annotations

import discord

from bot.models import ChartInfo, Song
from bot.ui.textfont import one_line


_PAGE_SIZE = 15


class ChartListView(discord.ui.View):
    def __init__(
        self,
        *,
        owner_id: int,
        rows: list[tuple[Song, ChartInfo]],
        heading: str,
        page_size: int = _PAGE_SIZE,
    ) -> None:
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.rows = rows
        self.heading = heading
        self.page_size = page_size
        self.page = 0
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
        pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        current = self.rows[self.page * self.page_size : (self.page + 1) * self.page_size]
        lines = [f"**Charts** {self.heading}", f"{len(self.rows)} charts"]
        if not current:
            lines.append("No charts match that filter.")
        for song, chart in current:
            level = chart.level_text or f"{chart.level:g}"
            lines.append(f"• **{one_line(song.title)}** `{chart.difficulty}` {level}")
        lines.append(f"Page {self.page + 1}/{pages}")
        text = "\n".join(lines)
        if len(text) <= 2000:
            return text
        return text[:1999].rstrip() + "…"

    def _update_buttons(self) -> None:
        pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        self.previous_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= pages - 1

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(content=self.render(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        self.page = min(pages - 1, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(content=self.render(), view=self)
