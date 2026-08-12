import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "bot.db"
DB_PATH.parent.mkdir(exist_ok=True)


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                message_count INTEGER DEFAULT 0,
                last_seen TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS task_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_name TEXT,
                run_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                details TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS dm_sequences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                messages_sent INTEGER NOT NULL DEFAULT 1,
                total_messages INTEGER NOT NULL DEFAULT 5,
                next_send_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (guild_id, user_id)
            )
        """)

        # Makes the recurring "find due DMs" query faster.
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_dm_sequences_due
            ON dm_sequences (active, next_send_at)
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS premium_users (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                message_count INTEGER DEFAULT 0,
                last_seen TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                premium_at TIMESTAMP
            )
        """)

        await db.commit()


async def increment_user_message(user_id: str, username: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, username, message_count, last_seen)
            VALUES (?, ?, 1, datetime('now', 'localtime'))
            ON CONFLICT(user_id) DO UPDATE SET
                username = ?,
                message_count = message_count + 1,
                last_seen = datetime('now', 'localtime')
        """, (user_id, username, username))

        await db.commit()


async def log_task_run(task_name: str, details: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO task_log (task_name, details) VALUES (?, ?)",
            (task_name, details)
        )

        await db.commit()


async def start_dm_sequence(
    guild_id: int,
    user_id: int,
    messages_sent: int = 1,
    total_messages: int = 5,
) -> bool:
    """
    Create a DM sequence after Day 1 has been sent.

    Returns True if a new sequence was created.
    Returns False if that user already has a sequence record.
    """

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO dm_sequences (
                guild_id,
                user_id,
                messages_sent,
                total_messages,
                next_send_at,
                active
            )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                datetime('now', 'localtime', '+1 day'),
                1
            )
            ON CONFLICT(guild_id, user_id) DO NOTHING
        """, (
            str(guild_id),
            str(user_id),
            messages_sent,
            total_messages,
        ))

        await db.commit()

        # True means the database inserted a new sequence.
        return cursor.rowcount == 1


async def get_due_dm_sequences() -> list[dict]:
    """
    Return every active sequence whose next daily DM is due.

    The returned dictionaries support:
    sequence["id"]
    sequence["guild_id"]
    sequence["user_id"]
    sequence["messages_sent"]
    sequence["total_messages"]
    """

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute("""
            SELECT
                id,
                guild_id,
                user_id,
                messages_sent,
                total_messages,
                next_send_at,
                active
            FROM dm_sequences
            WHERE active = 1
              AND messages_sent < total_messages
              AND next_send_at <= datetime('now', 'localtime')
            ORDER BY next_send_at ASC
        """)

        rows = await cursor.fetchall()

        return [dict(row) for row in rows]


async def mark_dm_sequence_sent(
    sequence_id: int,
    messages_sent: int,
    total_messages: int,
) -> bool:
    """
    Update the sequence after a DM successfully sends.

    If the final message was sent, active becomes 0.
    Otherwise, schedule the next message for 24 hours later.
    """

    is_complete = messages_sent >= total_messages

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            UPDATE dm_sequences
            SET
                messages_sent = ?,
                active = CASE
                    WHEN ? = 1 THEN 0
                    ELSE 1
                END,
                next_send_at = CASE
                    WHEN ? = 1 THEN next_send_at
                    ELSE datetime('now', 'localtime', '+1 day')
                END
            WHERE id = ?
              AND active = 1
        """, (
            messages_sent,
            int(is_complete),
            int(is_complete),
            sequence_id,
        ))

        await db.commit()

        return cursor.rowcount == 1


async def cancel_dm_sequence(
    guild_id: int,
    user_id: int,
) -> bool:
    """
    Stop future DMs for this server/member combination.

    This should be called when the paid subscription role is assigned.
    """

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            UPDATE dm_sequences
            SET active = 0
            WHERE guild_id = ?
              AND user_id = ?
              AND active = 1
        """, (
            str(guild_id),
            str(user_id),
        ))

        await db.commit()

        return cursor.rowcount == 1


async def remove_departed_user(
    guild_id: int,
    user_id: int,
) -> dict[str, int]:
    """
    Permanently remove a user's data when they leave, are kicked, or are banned.

    dm_sequences is scoped to one guild.
    users and premium_users are globally scoped by user_id in the current schema.
    """

    async with aiosqlite.connect(DB_PATH) as db:
        dm_cursor = await db.execute("""
            DELETE FROM dm_sequences
            WHERE guild_id = ?
              AND user_id = ?
        """, (
            str(guild_id),
            str(user_id),
        ))

        users_cursor = await db.execute("""
            DELETE FROM users
            WHERE user_id = ?
        """, (str(user_id),))

        premium_cursor = await db.execute("""
            DELETE FROM premium_users
            WHERE user_id = ?
        """, (str(user_id),))

        await db.commit()

        return {
            "dm_sequences": dm_cursor.rowcount,
            "users": users_cursor.rowcount,
            "premium_users": premium_cursor.rowcount,
        }