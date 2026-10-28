"""Private, paginated achievement checklist for /achievements."""

from __future__ import annotations

import discord


_COPY = {
    "en": ("Achievements", "Unlocked", "Locked", "Unlocked", "Page", "No achievements match this filter.", "Unlock"),
    "zh-Hans": ("\u6210\u5c31\u6536\u96c6\u518c", "\u5df2\u89e3\u9501", "\u672a\u89e3\u9501", "\u5df2\u89e3\u9501", "\u9875", "\u6ca1\u6709\u7b26\u5408\u6761\u4ef6\u7684\u6210\u5c31\u3002", "\u89e3\u9501\u65b9\u6cd5"),
    "zh-Hant": ("\u6210\u5c31\u6536\u85cf\u518a", "\u5df2\u89e3\u9396", "\u672a\u89e3\u9396", "\u5df2\u89e3\u9396", "\u9801", "\u6c92\u6709\u7b26\u5408\u689d\u4ef6\u7684\u6210\u5c31\u3002", "\u89e3\u9396\u65b9\u6cd5"),
    "ja": ("\u5b9f\u7e3e\u30b3\u30ec\u30af\u30bf\u30fc", "\u89e3\u9664\u6e08\u307f", "\u672a\u89e3\u9664", "\u89e3\u9664\u6e08\u307f", "\u30da\u30fc\u30b8", "\u8a72\u5f53\u3059\u308b\u5b9f\u7e3e\u306f\u3042\u308a\u307e\u305b\u3093\u3002", "\u89e3\u9664\u65b9\u6cd5"),
}


class AchievementChecklistView(discord.ui.View):
    def __init__(self, *, owner_id: int, rows: list[dict[str, str]], unlocked: set[str], total: int, language: str, page_size: int = 8) -> None:
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.rows = rows
        self.unlocked = unlocked
        self.total = total
        self.language = language if language in _COPY else "en"
        self.page_size = page_size
        self.page = 0
        self.previous_button.label = {"zh-Hans": "\u4e0a\u4e00\u9875", "zh-Hant": "\u4e0a\u4e00\u9801", "ja": "\u524d\u3078"}.get(self.language, "Previous")
        self.next_button.label = {"zh-Hans": "\u4e0b\u4e00\u9875", "zh-Hant": "\u4e0b\u4e00\u9801", "ja": "\u6b21\u3078"}.get(self.language, "Next")
        self._update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the person who opened this checklist can use these buttons.", ephemeral=True)
            return False
        return True

    def render(self) -> str:
        title, unlocked_label, locked_label, progress_label, page_label, empty_text, unlock_label = _COPY[self.language]
        pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        current = self.rows[self.page * self.page_size : (self.page + 1) * self.page_size]
        lines = [f"**{title}** | {progress_label} {len(self.unlocked)} / {self.total}"]
        if not current:
            lines.append(empty_text)
        for row in current:
            is_unlocked = row["id"] in self.unlocked
            mark = "[x]" if is_unlocked else "[ ]"
            state = unlocked_label if is_unlocked else locked_label
            lines.append(f"{mark} **{row['name']}** - *{row['title']}* | {state}")
            if not is_unlocked:
                lines.append(f"  -> {unlock_label}: {row['unlock']}")
        lines.append(f"{page_label} {self.page + 1}/{pages}")
        return "\n".join(lines)

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
