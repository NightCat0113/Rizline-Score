"""Private, paginated score target plan for /recommend."""

from __future__ import annotations

import discord


class RecommendationPlanView(discord.ui.View):
    def __init__(self, *, owner_id: int, increase: float | None, rows: list[dict], page_size: int = 8) -> None:
        super().__init__(timeout=180)
        self.owner_id = owner_id
        self.increase = increase
        self.rows = rows
        self.page_size = page_size
        self.page = 0
        self._update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who requested this plan can use these buttons.", ephemeral=True
            )
            return False
        return True

    def render(self) -> str:
        pages = max(1, (len(self.rows) + self.page_size - 1) // self.page_size)
        start = self.page * self.page_size
        current = self.rows[start : start + self.page_size]
        total_gain = sum(row["rks_gain"] for row in self.rows)
        if self.increase is None:
            title = f"**Score targets for max score-only gain (+{total_gain:.3f} RKS)**"
        else:
            title = f"**Score targets for +{self.increase:.2f} RKS**"
        lines = [
            title,
            f"Combined plan: about +{total_gain:.3f} overall RKS.",
        ]
        if self.increase is not None and total_gain + 1e-6 < self.increase:
            lines.append(
                f"Requested +{self.increase:.2f}; this score-only plan reaches about +{total_gain:.3f}."
            )
        lines.extend(
            [
                "Only scored charts are included. Targets assume the current accuracy tier stays the same; outside charts must score high enough to enter the Best 40.",
                "",
            ]
        )
        for row in current:
            lines.append(
                f"• **{row['title']}** `{row['difficulty']}`: "
                f"{row['current_score']:,} → **{row['target_score']:,}** "
                f"(about +{row['rks_gain']:.3f} overall RKS"
                f"{'' if row.get('in_top40') else '; enter the Best 40'})"
            )
        lines.append(f"Page {self.page + 1}/{pages}")
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
