import datetime
import logging

import discord
from discord.ext import commands, tasks

from database import (
    increment_user_message,
    log_task_run,
    start_dm_sequence,
    has_dm_sequence,
    get_due_dm_sequences,
    mark_dm_sequence_sent,
    cancel_dm_sequence,
    remove_departed_user,
)

VERIFIED_ROLE_ID = 1214707048596381726
PAID_SUBSCRIPTION_ROLE_ID = 1250962210465779714
CHAT_CHANNEL_ID = 1214705314826559540

TOTAL_SEQUENCE_DMS = 5
DM_SEQUENCE_CHECK_MINUTES = 15
VERIFIED_DM_BACKFILL_HOURS = 6


class EventCog(commands.Cog, name="Events"):
    """Event listeners and background automation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.process_dm_sequences.start()
        self.backfill_verified_dm_sequences.start()
        self.auto_cleanup.start()

    def cog_unload(self):
        """Stop background loops cleanly when the cog unloads."""
        self.process_dm_sequences.cancel()
        self.backfill_verified_dm_sequences.cancel()
        self.auto_cleanup.cancel()

    def build_sequence_embed(
        self,
        member: discord.Member,
        day: int,
        title: str,
        description: str,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.magenta(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )

        embed.set_author(
            name=f"Welcome Series — Day {day} of {TOTAL_SEQUENCE_DMS}",
            icon_url=member.guild.icon.url if member.guild.icon else None,
        )

        embed.set_footer(
            text="Only Funds - Opus @ 2026",
            icon_url=self.bot.user.display_avatar.url if self.bot.user else None,
        )

        return embed

    async def send_day_one_and_start_sequence(
        self,
        member: discord.Member,
        source: str,
    ) -> bool:
        """
        Send Day 1 and then create the database sequence record.

        A database record is only created after the DM sends successfully.
        This prevents users with closed DMs from being incorrectly marked as
        having received Day 1.

        Returns True only if Day 1 was sent and a new sequence was created.
        """

        if member.bot:
            return False

        has_verified_role = any(
            role.id == VERIFIED_ROLE_ID
            for role in member.roles
        )

        has_paid_role = any(
            role.id == PAID_SUBSCRIPTION_ROLE_ID
            for role in member.roles
        )

        if not has_verified_role:
            return False

        if has_paid_role:
            return False

        sequence_exists = await has_dm_sequence(
            guild_id=member.guild.id,
            user_id=member.id,
        )

        if sequence_exists:
            logging.info(
                "DM sequence already exists for %s; source=%s.",
                member,
                source,
            )
            return False

        chat = member.guild.get_channel(CHAT_CHANNEL_ID)

        if chat is None:
            logging.error(
                "Cannot start DM sequence for %s: channel %s was not found.",
                member.id,
                CHAT_CHANNEL_ID,
            )
            return False

        first_sequence_embed = self.build_sequence_embed(
            member=member,
            day=1,
            title="🎉 You're Officially Verified!",
            description=(
                f"Hey {member.mention} — thanks for verifying! You're all set "
                "and the full server is open to you now.\n\n"
                "As promised, here's your free trading guide. Give it a read "
                "when you get a chance.\n\n"
                "Quick question to kick things off: where are you at with "
                "futures trading right now? Still learning the basics, actively "
                "trading, or somewhere in between? No wrong answer — just want "
                "to make sure you get the most out of being here.\n\n"
                f"Let me know in {chat.mention}."
            ),
        )

        first_sequence_embed.set_image(
            url=(
                "https://cdn.discordapp.com/attachments/1054139443344310442/"
                "1535459972022935663/BTE_Lvl1_Guide.png"
                "?ex=6a77d808&is=6a768688"
                "&hm=78a311aa9cb5c71383fb044f4c3e95ec51b4f559533f3aa5ad0dfc2cfe1eb7f9&"
            )
        )

        try:
            await member.send(embed=first_sequence_embed)

        except discord.Forbidden:
            logging.info(
                "Could not send Day 1 DM to %s; their DMs are disabled.",
                member,
            )
            return False

        except discord.HTTPException as error:
            logging.error(
                "Discord failed to send Day 1 to %s: %s",
                member,
                error,
                exc_info=True,
            )
            return False

        sequence_started = await start_dm_sequence(
            guild_id=member.guild.id,
            user_id=member.id,
            messages_sent=1,
            total_messages=TOTAL_SEQUENCE_DMS,
        )

        if not sequence_started:
            logging.warning(
                "Day 1 was sent to %s, but the sequence already existed. "
                "Source=%s.",
                member,
                source,
            )
            return False

        await log_task_run(
            "dm_sequence_started",
            f"Started verified DM sequence for {member} "
            f"in {member.guild.name}; source={source}",
        )

        logging.info(
            "✅ Started Day 1 DM sequence for %s; source=%s.",
            member,
            source,
        )

        return True

    # ───────────────────────────────────────
    # EVENT LISTENERS
    # ───────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        await increment_user_message(
            str(message.author.id),
            message.author.name,
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await log_task_run(
            "member_join",
            f"{member} joined {member.guild.name} (ID: {member.guild.id})",
        )

        logging.info(
            "➕ %s joined %s",
            member,
            member.guild.name,
        )

        try:
            embed = discord.Embed(
                title=f"🎉 Welcome to {member.guild.name}!",
                description=(
                    f"Hey, {member.mention}! Welcome in — really glad you're here.\n\n"
                    "I'm Isaac. I built this space for traders who are serious "
                    "about getting better, whether you're just starting out or "
                    "you've been at it a while.\n\n"
                    "One quick step before you dive in: click the free link above "
                    "to verify your account. Takes about 10 seconds and it "
                    "unlocks the full server.\n\n"
                    "And as a thank-you for verifying, I'll drop you my free "
                    "trading guide. It's the same foundation I'd want every new "
                    "trader here to start from.\n\n"
                    "See you inside.\n\n"
                    "https://whop.com/joined/big-tick-energy-premium-copy/"
                    "products/discord-access-c6/"
                ),
                color=discord.Color.magenta(),
                timestamp=datetime.datetime.now(datetime.timezone.utc),
                url=(
                    "https://whop.com/joined/big-tick-energy-premium-copy/"
                    "products/discord-access-c6/"
                ),
            )

            embed.set_image(
                url=(
                    "https://media.giphy.com/media/v1.Y2lkPWVjZjA1ZTQ3"
                    "N3NyY2NkdmM3aWJkajRxaWI4eWhqNm95MTNwdWd1MHRsbzlidzQzbi"
                    "ZlcD12MV9naWZzX3NlYXJjaCZjdD1n/dtkm9ArrjbvTMWzjuB/giphy.gif"
                )
            )

            embed.set_footer(
                text="Only Funds - Opus @ 2026",
                icon_url=self.bot.user.display_avatar.url if self.bot.user else None,
            )

            await member.send(embed=embed)

            logging.info("Sent welcome DM to %s", member)

        except discord.Forbidden:
            logging.info(
                "Could not send welcome DM to %s; their DMs are disabled.",
                member,
            )

        except Exception as error:
            logging.error(
                "Welcome DM failed for %s: %s",
                member,
                error,
                exc_info=True,
            )

    @staticmethod
    async def cleanup_departed_member(
        guild: discord.Guild,
        user: discord.abc.User,
        removal_type: str,
    ):
        """Delete stored user data after a leave, kick, or ban."""
        try:
            deleted = await remove_departed_user(
                guild_id=guild.id,
                user_id=user.id,
            )

            await log_task_run(
                "member_data_removed",
                (
                    f"{user.mention} ({user.name}) ({user.id}) was removed "
                    f"from {guild.name} ({guild.id}) via {removal_type}. "
                    f"Deleted: dm_sequences={deleted['dm_sequences']}, "
                    f"users={deleted['users']}, "
                    f"premium_users={deleted['premium_users']}"
                ),
            )

            logging.info(
                "🗑️ Removed database data for %s (%s) from %s via %s. "
                "Deleted: %s",
                user,
                user.id,
                guild.name,
                removal_type,
                deleted,
            )

        except Exception as error:
            logging.error(
                "Failed to remove database data for %s (%s) from %s: %s",
                user,
                user.id,
                guild.name,
                error,
                exc_info=True,
            )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Fires when a member leaves, is kicked, or is banned."""
        await self.cleanup_departed_member(
            guild=member.guild,
            user=member,
            removal_type="leave/kick/ban",
        )

    @commands.Cog.listener()
    async def on_member_ban(
        self,
        guild: discord.Guild,
        user: discord.User,
    ):
        """
        Backup cleanup for bans.

        A ban can also produce on_member_remove, so this may run after the
        first deletion. remove_departed_user is safe to run more than once.
        """
        await self.cleanup_departed_member(
            guild=guild,
            user=user,
            removal_type="ban",
        )

    @commands.Cog.listener()
    async def on_member_update(
        self,
        before: discord.Member,
        after: discord.Member,
    ):
        """
        Start the verified-user DM sequence when VERIFIED_ROLE_ID is newly added.
        Stop future sequence DMs when the paid role is added.
        """

        had_verified_role = any(
            role.id == VERIFIED_ROLE_ID
            for role in before.roles
        )

        has_verified_role = any(
            role.id == VERIFIED_ROLE_ID
            for role in after.roles
        )

        had_paid_role = any(
            role.id == PAID_SUBSCRIPTION_ROLE_ID
            for role in before.roles
        )

        has_paid_role = any(
            role.id == PAID_SUBSCRIPTION_ROLE_ID
            for role in after.roles
        )

        # Paid role was just added: stop all remaining sequence DMs.
        if not had_paid_role and has_paid_role:
            await cancel_dm_sequence(
                guild_id=after.guild.id,
                user_id=after.id,
            )

            await log_task_run(
                "dm_sequence_cancelled_paid",
                f"Stopped DM sequence for paid subscriber {after} "
                f"in {after.guild.name}",
            )

            logging.info(
                "💳 Paid role assigned to %s — sequence cancelled.",
                after,
            )
            return

        # Only begin Day 1 if verified was newly added.
        if had_verified_role or not has_verified_role:
            return

        # Never begin a sequence for an already-paid member.
        if has_paid_role:
            await log_task_run(
                "dm_sequence_skipped_paid",
                f"Skipped DM sequence for paid subscriber {after} "
                f"in {after.guild.name}",
            )

            logging.info(
                "💳 %s is verified but already paid — skipping DM sequence.",
                after,
            )
            return

        await self.send_day_one_and_start_sequence(
            member=after,
            source="verified_role_added",
        )

    # ───────────────────────────────────────
    # DM SEQUENCE BACKGROUND TASK
    # ───────────────────────────────────────

    @tasks.loop(minutes=DM_SEQUENCE_CHECK_MINUTES)
    async def process_dm_sequences(self):
        """
        Poll the database for active sequences that are due.

        The send interval is controlled in database.py:
        - start_dm_sequence() schedules Day 2 for 24 hours later.
        - mark_dm_sequence_sent() schedules each later message.
        - get_due_dm_sequences() returns records whose next_send_at is due.
        """
        try:
            due_sequences = await get_due_dm_sequences()

            logging.info(
                "DM sequence check found %s due sequence(s).",
                len(due_sequences),
            )

        except Exception as error:
            logging.error(
                "Could not retrieve due DM sequences: %s",
                error,
                exc_info=True,
            )
            return

        for sequence in due_sequences:
            try:
                sequence_id = sequence["id"]
                guild_id = int(sequence["guild_id"])
                user_id = int(sequence["user_id"])
                messages_sent = int(sequence["messages_sent"])
                total_messages = int(sequence["total_messages"])

                guild = self.bot.get_guild(guild_id)

                if guild is None:
                    logging.warning(
                        "Sequence %s skipped: guild %s is unavailable.",
                        sequence_id,
                        guild_id,
                    )
                    continue

                member = guild.get_member(user_id)

                if member is None:
                    try:
                        member = await guild.fetch_member(user_id)

                    except discord.NotFound:
                        logging.info(
                            "Sequence %s cancelled: user %s is no longer in "
                            "guild %s.",
                            sequence_id,
                            user_id,
                            guild_id,
                        )

                        await cancel_dm_sequence(
                            guild_id=guild_id,
                            user_id=user_id,
                        )
                        continue

                    except discord.HTTPException as error:
                        logging.error(
                            "Could not fetch user %s for sequence %s: %s",
                            user_id,
                            sequence_id,
                            error,
                        )
                        continue

                is_paid_subscriber = any(
                    role.id == PAID_SUBSCRIPTION_ROLE_ID
                    for role in member.roles
                )

                if is_paid_subscriber:
                    await cancel_dm_sequence(
                        guild_id=guild_id,
                        user_id=user_id,
                    )

                    logging.info(
                        "💳 Sequence %s cancelled because %s is paid.",
                        sequence_id,
                        member,
                    )
                    continue

                next_message_number = messages_sent + 1

                if next_message_number > total_messages:
                    logging.info(
                        "Sequence %s is complete; no additional message needed.",
                        sequence_id,
                    )
                    continue

                sequence_messages = {
                    2: {
                        "title": "",
                        "description": (
                            f"Hey {member.mention} — hope you've had a chance "
                            "to look around the server a bit. Wanted to drop "
                            "something useful in your lap right away.\n\n"
                            "One of the biggest mistakes I see newer futures "
                            "traders make is jumping into trades without having "
                            "their daily levels mapped out first. Levels give "
                            "you your roadmap for the day — without them, you're "
                            "basically navigating blind.\n\n"
                            "This week I've been sharing my levels in the premium "
                            "community. Whether you're building out your own or "
                            "following mine, it's one of the simplest habits "
                            "that can tighten up your trading fast."
                        ),
                    },
                    3: {
                        "title": "",
                        "description": (
                            f"{member.mention}, quick story. When I started "
                            "trading futures, I blew through more than one "
                            "account before things clicked. Not because I "
                            "didn't know the setups — but because I had no "
                            "structure, no discipline, and no one showing me "
                            "what actually mattered.\n\n"
                            "What changed everything was having a repeatable "
                            "process and a community that kept me accountable. "
                            "That's exactly what I've tried to build here.\n\n"
                            "If you've had rough stretches, you're not alone — "
                            "it's part of the path. The traders who make it are "
                            "the ones who stick with the process."
                        ),
                    },
                    4: {
                        "title": "",
                        "description": (
                            f"{member.mention}, wanted to share what's behind "
                            "the Premium doors in case you're curious. Premium "
                            "members get my daily levels laid out every morning, "
                            "live trading sessions where you can watch the "
                            "process in real time, and the full MasterClass that "
                            "walks through my entire approach step by step.\n\n"
                            "It's the difference between watching from the "
                            "sidelines and actually being in the game with a "
                            "roadmap. No pressure at all — just want you to know "
                            "it's there when you're ready to go deeper."
                        ),
                    },
                    5: {
                        "title": "",
                        "description": (
                            f"Hey {member.mention} — if you've been thinking "
                            "about Premium but haven't pulled the trigger, I "
                            "get it. The two things I hear most are 'is it worth "
                            "it' and 'will I actually use it.'\n\n"
                            "Here's my honest take: the members who get the most "
                            "out of it are the ones who show up to the live "
                            "sessions and follow the daily levels consistently. "
                            "It's not magic — it's structure and repetition. If "
                            "you're willing to show up, it works. And you're not "
                            "locked in — you can see if it fits and go from there."
                        ),
                    },
                }

                embed_data = sequence_messages.get(next_message_number)

                if embed_data is None:
                    logging.warning(
                        "Sequence %s has no configured content for message %s.",
                        sequence_id,
                        next_message_number,
                    )
                    continue

                sequence_embed = self.build_sequence_embed(
                    member=member,
                    day=next_message_number,
                    title=embed_data["title"],
                    description=embed_data["description"],
                )

                await member.send(embed=sequence_embed)

                await mark_dm_sequence_sent(
                    sequence_id=sequence_id,
                    messages_sent=next_message_number,
                    total_messages=total_messages,
                )

                await log_task_run(
                    "dm_sequence_sent",
                    f"Sent sequence DM {next_message_number}/{total_messages} "
                    f"to {member}",
                )

                logging.info(
                    "✅ Sent DM %s/%s to %s for sequence %s.",
                    next_message_number,
                    total_messages,
                    member,
                    sequence_id,
                )

            except discord.Forbidden:
                logging.info(
                    "Could not DM user %s for sequence %s; marking sequence "
                    "complete.",
                    sequence.get("user_id"),
                    sequence.get("id"),
                )

                await mark_dm_sequence_sent(
                    sequence_id=sequence["id"],
                    messages_sent=sequence["total_messages"],
                    total_messages=sequence["total_messages"],
                )

            except Exception as error:
                logging.error(
                    "Failed processing sequence %s for user %s: %s",
                    sequence.get("id"),
                    sequence.get("user_id"),
                    error,
                    exc_info=True,
                )

    @process_dm_sequences.before_loop
    async def before_process_dm_sequences(self):
        await self.bot.wait_until_ready()
        logging.info("DM sequence processor is ready.")

    # ───────────────────────────────────────
    # VERIFIED DM BACKFILL CHECKER
    # ───────────────────────────────────────

    @tasks.loop(hours=VERIFIED_DM_BACKFILL_HOURS)
    async def backfill_verified_dm_sequences(self):
        """
        Find verified members who have never received a sequence record.

        This protects against missed on_member_update events, such as when the
        bot was offline while the verified role was assigned.
        """

        for guild in self.bot.guilds:
            verified_role = guild.get_role(VERIFIED_ROLE_ID)

            if verified_role is None:
                logging.warning(
                    "Verified role %s was not found in %s.",
                    VERIFIED_ROLE_ID,
                    guild.name,
                )
                continue

            checked = 0
            started = 0
            skipped_paid = 0
            skipped_existing = 0

            try:
                async for member in guild.fetch_members(limit=None):
                    if member.bot:
                        continue

                    has_verified_role = any(
                        role.id == VERIFIED_ROLE_ID
                        for role in member.roles
                    )

                    if not has_verified_role:
                        continue

                    has_paid_role = any(
                        role.id == PAID_SUBSCRIPTION_ROLE_ID
                        for role in member.roles
                    )

                    if has_paid_role:
                        skipped_paid += 1
                        continue

                    checked += 1

                    sequence_exists = await has_dm_sequence(
                        guild_id=guild.id,
                        user_id=member.id,
                    )

                    if sequence_exists:
                        skipped_existing += 1
                        continue

                    try:
                        did_start = await self.send_day_one_and_start_sequence(
                            member=member,
                            source="verified_backfill_checker",
                        )

                        if did_start:
                            started += 1

                    except Exception as error:
                        logging.error(
                            "Backfill failed for %s in %s: %s",
                            member.id,
                            guild.name,
                            error,
                            exc_info=True,
                        )

                details = (
                    f"{guild.name}: checked={checked}, started={started}, "
                    f"skipped_existing={skipped_existing}, "
                    f"skipped_paid={skipped_paid}"
                )

                await log_task_run(
                    "verified_dm_backfill_check",
                    details,
                )

                logging.info(
                    "Verified-DM backfill complete: %s",
                    details,
                )

            except discord.Forbidden:
                logging.error(
                    "Cannot fetch members for %s. Confirm the bot has the "
                    "Server Members Intent enabled in both the Discord "
                    "Developer Portal and your bot code.",
                    guild.name,
                )

            except discord.HTTPException as error:
                logging.error(
                    "Failed to fetch members for %s: %s",
                    guild.name,
                    error,
                    exc_info=True,
                )

            except Exception as error:
                logging.error(
                    "Verified-DM backfill checker failed for %s: %s",
                    guild.name,
                    error,
                    exc_info=True,
                )

    @backfill_verified_dm_sequences.before_loop
    async def before_backfill_verified_dm_sequences(self):
        await self.bot.wait_until_ready()
        logging.info("Verified DM backfill checker is ready.")

    # ───────────────────────────────────────
    # BACKGROUND TASKS
    # ───────────────────────────────────────

    @tasks.loop(minutes=5)
    async def auto_cleanup(self):
        """Log a periodic bot and database health check."""
        try:
            uptime = getattr(self.bot, "uptime", 0)

            member_count = sum(
                guild.member_count or 0
                for guild in self.bot.guilds
            )

            details = (
                f"Bot uptime: {uptime:.1f}s | "
                f"Servers: {len(self.bot.guilds)} | "
                f"Members: {member_count}"
            )

            await log_task_run("auto_cleanup", details)

            logging.info("🧹 Cleanup task ran: %s", details)

        except Exception as error:
            logging.error(
                "❌ Cleanup task failed: %s",
                error,
                exc_info=True,
            )

    @auto_cleanup.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(EventCog(bot))