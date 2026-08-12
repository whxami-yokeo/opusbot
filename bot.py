# main.py
import os
import logging
from pathlib import Path
from datetime import datetime

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database import init_db

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DEV_GUILD_ID = int(os.getenv("DEV_GUILD_ID") or 0)

logging.basicConfig(level=logging.INFO)
intents = discord.Intents.all()


class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )
        self.started_at: datetime | None = None  # seconds since epoch

    async def setup_hook(self):
        self.started_at = datetime.now()  # record as early as possible
        await init_db()
        logging.info("✅ Database initialized")

        # Load cogs
        cog_dir = Path(__file__).parent / "cogs"
        for cog_file in cog_dir.glob("*.py"):
            if cog_file.name == "__init__.py":
                continue
            module_name = f"cogs.{cog_file.stem}"
            await self.load_extension(module_name)
            logging.info(f"✅ Loaded cog: {module_name}")

        # Sync slash commands (dev guild for instant testing)
        if DEV_GUILD_ID:
            self.tree.copy_global_to(guild=discord.Object(id=DEV_GUILD_ID))
            synced = await self.tree.sync(guild=discord.Object(id=DEV_GUILD_ID))
            logging.info(f"⚙️ Synced {len(synced)} slash commands to dev guild.")
        else:
            await self.tree.sync()
            logging.info("⚙️ Synced global slash commands.")

    async def on_ready(self):
        if self.started_at is None:
            self.started_at = datetime.now()
        logging.info(f"🟢 Logged in as {self.user} (ID: {self.user.id})")

    @property
    def uptime(self) -> float:
        """Returns uptime in seconds as a float."""
        if self.started_at is None:
            return 0.0
        return (datetime.now() - self.started_at).total_seconds()

    # In Bot class, main.py
    async def get_cog_commands(self) -> dict[str, list[commands.Command]]:
        """Group commands by cog for help display."""
        mapping = {}
        for cmd in self.commands:
            if cmd.hidden:
                continue
            cog_name = getattr(cmd.cog, "qualified_name", "No Category") or "No Category"
            if cog_name not in mapping:
                mapping[cog_name] = []
            mapping[cog_name].append(cmd)
        return mapping


bot = Bot()
bot.run(TOKEN)
