# cogs/core.py
import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
from database import DB_PATH


def format_uptime(seconds: float) -> str:
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{sec}s")
    return " ".join(parts)


def is_admin(member: discord.Member) -> bool:
    """Check if member has Administrator permission (covers owner via role or explicit grant)."""
    return member.guild_permissions.administrator


class Core(commands.Cog, name="Core"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ───────────────────────────────────────
    # UPTIME
    # ───────────────────────────────────────
    @commands.command(name="uptime", help="Show bot uptime")
    async def uptime_prefix(self, ctx: commands.Context):
        await self._uptime_action(ctx, is_prefix=True)

    @app_commands.command(name="uptime", description="Show bot uptime")
    async def uptime_slash(self, interaction: discord.Interaction):
        await self._uptime_action(interaction, is_prefix=False)

    async def _uptime_action(self, target, is_prefix: bool):
        uptime_sec = self.bot.uptime
        embed = discord.Embed(
            title="⏱️ Bot Uptime",
            description=f"**{format_uptime(uptime_sec)}**",
            color=discord.Color.green()
        )
        embed.add_field(name="Seconds", value=f"`{uptime_sec:.1f}`", inline=True)
        embed.add_field(name="Latency", value=f"`{round(self.bot.latency * 1000)}ms`", inline=True)
        if is_prefix:
            await target.send(embed=embed)
        else:
            await target.response.send_message(embed=embed, ephemeral=True)

    # ───────────────────────────────────────
    # STATS
    # ───────────────────────────────────────
    @commands.command(name="stats", help="View your message stats")
    async def stats_prefix(self, ctx: commands.Context):
        await self._stats_action(ctx, is_prefix=True)

    @app_commands.command(name="stats", description="View your message stats")
    async def stats_slash(self, interaction: discord.Interaction):
        await self._stats_action(interaction, is_prefix=False)

    @staticmethod
    async def _stats_action(target, is_prefix: bool):
        user = target.author if is_prefix else target.user
        user_id = str(user.id)
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                    "SELECT message_count, last_seen FROM users WHERE user_id = ?",
                    (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
        if row:
            embed = discord.Embed(title="📊 Your Stats", color=discord.Color.green())
            embed.add_field(name="Messages", value=str(row["message_count"]), inline=True)
            embed.add_field(name="Last Seen", value=row["last_seen"], inline=True)
        else:
            embed = discord.Embed(
                title="❓ No Data",
                description="You haven’t sent any messages yet — say something!",
                color=discord.Color.orange()
            )
        if is_prefix:
            await target.send(embed=embed)
        else:
            await target.response.send_message(embed=embed, ephemeral=True)

    # ───────────────────────────────────────
    # INFO
    # ───────────────────────────────────────
    @commands.command(name="info", help="Bot info + DB status")
    async def info_prefix(self, ctx: commands.Context):
        await self._info_action(ctx, is_prefix=True)

    @app_commands.command(name="info", description="Bot info + DB status")
    async def info_slash(self, interaction: discord.Interaction):
        await self._info_action(interaction, is_prefix=False)

    async def _info_action(self, target, is_prefix: bool):
        uptime_sec = self.bot.uptime

        # Total members across all servers the bot can access.
        # A user in multiple servers will be counted once per server.
        available_users = sum(guild.member_count or 0 for guild in self.bot.guilds)

        embed = discord.Embed(title="🤖 Bot Info", color=discord.Color.blue())
        embed.add_field(name="Name", value=self.bot.user.name, inline=True)
        embed.add_field(name="Servers", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Users", value=str(available_users), inline=True)
        embed.add_field(name="Uptime", value=format_uptime(uptime_sec), inline=True)

        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("SELECT 1")
            db_status = "✅ Healthy"
        except Exception as e:
            db_status = f"❌ {e}"

        embed.add_field(name="Database", value=db_status, inline=False)

        if is_prefix:
            await target.send(embed=embed)
        else:
            await target.response.send_message(embed=embed, ephemeral=True)

    # ───────────────────────────────────────
    # ADMIN: RELOAD (Admin-Only)
    # ───────────────────────────────────────
    @commands.command(name="reload", help="Reload a cog (admin only)")
    async def reload_prefix(self, ctx: commands.Context, cog_name: str):
        await self._reload_action(ctx, cog_name, is_prefix=True)

    @app_commands.command(name="reload", description="Reload a cog (admin only)")
    @app_commands.describe(cog_name="Name of the cog to reload (e.g., core, fun)")
    async def reload_slash(self, interaction: discord.Interaction, cog_name: str):
        await self._reload_action(interaction, cog_name, is_prefix=False)

    async def _reload_action(self, target, cog_name: str, is_prefix: bool):
        member = target.author if is_prefix else target.user
        if not is_admin(member):
            msg = "⛔ This command is **admin-only**."
            if is_prefix:
                await target.send(msg, delete_after=10)
            else:
                await target.response.send_message(msg, ephemeral=True, delete_after=10)
            return

        try:
            await self.bot.reload_extension(f"cogs.{cog_name}")
            desc = f"✅ Reloaded cog: `{cog_name}`"
            color = discord.Color.green()
        except Exception as e:
            desc = f"❌ Failed to reload `{cog_name}`: `{e}`"
            color = discord.Color.red()

        embed = discord.Embed(title="🔄 Reloaded", description=desc, color=color)
        if is_prefix:
            await target.send(embed=embed)
        else:
            await target.response.send_message(embed=embed, ephemeral=False)

    # ───────────────────────────────────────
    # CUSTOM HELP COMMAND (Auto-Generated, Clean)
    # ───────────────────────────────────────
    @commands.command(name="help", help="Show this help message")
    async def help_prefix(self, ctx: commands.Context, *, command: str | None = None):
        await self._help_action(ctx, command, is_prefix=True)

    async def _help_action(self, target, cmd_name: str | None, is_prefix: bool):
        prefix = target.clean_prefix if hasattr(target, "clean_prefix") else "/"
        bot = self.bot

        # Specific command help
        if cmd_name:
            cmd = bot.get_command(cmd_name)
            if not cmd:
                msg = f"❓ Command `{cmd_name}` not found."
                if is_prefix:
                    await target.send(msg)
                else:
                    await target.response.send_message(msg, ephemeral=True)
                return
            embed = discord.Embed(
                title=f"`{prefix}{cmd.qualified_name} {cmd.signature}`",
                description=cmd.help or "No description available.",
                color=discord.Color.random()
            )
            if cmd.aliases:
                embed.add_field(name="Aliases", value=", ".join(f"`{a}`" for a in cmd.aliases), inline=False)
            # Show usage examples if in docstring (optional enhancement)
            if is_prefix:
                await target.send(embed=embed)
            else:
                await target.response.send_message(embed=embed, ephemeral=True)
            return

        # Bot-wide help: group by cog
        embed = discord.Embed(
            title="📘 Help",
            description=f"Use `{prefix}help <command>` for details.\n"
                        f"🔒 Admin commands require **Administrator** permission.",
            color=discord.Color.blurple()
        )

        # Fallback: group manually if get_cog_commands not available (discord.py <2.5)
        mapping = await bot.get_cog_commands()

        for cog_name, cmds in sorted(mapping.items()):
            filtered = [c for c in cmds if await c.can_run(target) if not c.hidden]
            if not filtered:
                continue
            lines = []
            for cmd in sorted(filtered, key=lambda c: c.name):
                sig = f"`{prefix}{cmd.qualified_name} {cmd.signature}`"
                help_text = (cmd.help or "No description").splitlines()[0][:50]
                lines.append(f"{sig} — {help_text}")
            embed.add_field(name=f"**{cog_name}**", value="\n".join(lines), inline=False)

        # Footer
        embed.set_footer(text=f"Requested by {target.author}", icon_url=target.author.display_avatar.url)

        if is_prefix:
            await target.send(embed=embed)
        else:
            await target.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Core(bot))
