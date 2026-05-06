"""
PostgreSQL-backed conversation client that implements the same interface as
CosmosConversationClient. When CHAT_HISTORY_BACKEND is set to "postgresql" this
client handles all conversation/message persistence.

Schema (auto-created on first use via :meth:`ensure`):

    conversations
        id              TEXT PRIMARY KEY
        user_id         TEXT NOT NULL
        title           TEXT
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()

    messages
        id              TEXT PRIMARY KEY
        conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE
        user_id         TEXT NOT NULL
        role            TEXT NOT NULL
        content         JSONB NOT NULL
        feedback        TEXT
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
"""

import logging
import uuid
from datetime import datetime, timezone

import asyncpg

logger = logging.getLogger(__name__)

_CREATE_CONVERSATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    title       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_CREATE_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    role            TEXT NOT NULL,
    content         JSONB NOT NULL,
    feedback        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_conversation
        FOREIGN KEY (conversation_id)
        REFERENCES conversations(id)
        ON DELETE CASCADE
);
"""

_CREATE_IDX_CONVERSATIONS_USER = """
CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
"""

_CREATE_IDX_MESSAGES_CONVERSATION = """
CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgreSQLConversationClient:
    """Async PostgreSQL client for conversation/message persistence.

    A single :class:`asyncpg.Pool` is shared for the lifetime of the object.
    Call :meth:`ensure` once on startup to verify connectivity and create the
    schema.  Call :meth:`close` during shutdown to release the pool.

    The ``close()`` method exists so that call-sites that call
    ``cosmosdb_client.close()`` continue to work without changes.
    """

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        enable_message_feedback: bool = False,
        min_connections: int = 1,
        max_connections: int = 10,
    ):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.enable_message_feedback = enable_message_feedback
        self._min_connections = min_connections
        self._max_connections = max_connections
        self._pool: asyncpg.Pool | None = None

        # Shim so that code calling ``client.cosmosdb_client.close()`` works.
        self.cosmosdb_client = self

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                min_size=self._min_connections,
                max_size=self._max_connections,
            )
        return self._pool

    @staticmethod
    def _row_to_conversation(row) -> dict:
        return {
            "id": row["id"],
            "type": "conversation",
            "userId": row["user_id"],
            "title": row["title"],
            "createdAt": row["created_at"].isoformat(),
            "updatedAt": row["updated_at"].isoformat(),
            "conversation_id": row["id"],
        }

    @staticmethod
    def _row_to_message(row) -> dict:
        content = row["content"]
        # asyncpg returns JSONB as a dict; keep it consistent with CosmosDB
        if isinstance(content, str):
            import json
            content = json.loads(content)
        msg = {
            "id": row["id"],
            "type": "message",
            "userId": row["user_id"],
            "conversationId": row["conversation_id"],
            "role": row["role"],
            "content": content,
            "createdAt": row["created_at"].isoformat(),
            "updatedAt": row["updated_at"].isoformat(),
        }
        if row["feedback"] is not None:
            msg["feedback"] = row["feedback"]
        return msg

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def ensure(self):
        """Verify connectivity and create tables/indexes if they don't exist.

        Returns ``(True, "...")`` on success, ``(False, error_message)`` on failure.
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(_CREATE_CONVERSATIONS_TABLE)
                await conn.execute(_CREATE_MESSAGES_TABLE)
                await conn.execute(_CREATE_IDX_CONVERSATIONS_USER)
                await conn.execute(_CREATE_IDX_MESSAGES_CONVERSATION)
            logger.info("PostgreSQL schema verified/created successfully")
            return True, "PostgreSQL client initialized successfully"
        except Exception as exc:
            logger.exception("Failed to ensure PostgreSQL schema")
            return False, str(exc)

    async def close(self):
        """Release the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    async def create_conversation(
        self, user_id: str, conversation_id: str = None, title: str = ""
    ) -> dict:
        if conversation_id is None:
            conversation_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO conversations (id, user_id, title, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $4)
                ON CONFLICT (id) DO UPDATE
                    SET title = EXCLUDED.title,
                        updated_at = EXCLUDED.updated_at
                RETURNING id, user_id, title, created_at, updated_at
                """,
                conversation_id,
                user_id,
                title,
                now,
            )
        return self._row_to_conversation(row)

    async def upsert_conversation(self, conversation: dict) -> dict:
        now = datetime.now(timezone.utc)
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO conversations (id, user_id, title, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (id) DO UPDATE
                    SET title = EXCLUDED.title,
                        updated_at = EXCLUDED.updated_at
                RETURNING id, user_id, title, created_at, updated_at
                """,
                conversation["id"],
                conversation.get("userId", conversation.get("user_id", "")),
                conversation.get("title", ""),
                _parse_dt(conversation.get("createdAt")) or now,
                now,
            )
        return self._row_to_conversation(row)

    async def delete_conversation(self, user_id: str, conversation_id: str):
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM conversations WHERE id = $1 AND user_id = $2",
                conversation_id,
                user_id,
            )

    async def get_conversations(
        self,
        user_id: str,
        limit: int = None,
        sort_order: str = "DESC",
        offset: int = 0,
    ) -> list:
        sort_order = "DESC" if sort_order.upper() != "ASC" else "ASC"
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if limit is not None:
                rows = await conn.fetch(
                    f"""
                    SELECT id, user_id, title, created_at, updated_at
                    FROM conversations
                    WHERE user_id = $1
                    ORDER BY updated_at {sort_order}
                    LIMIT $2 OFFSET $3
                    """,
                    user_id,
                    limit,
                    offset,
                )
            else:
                rows = await conn.fetch(
                    f"""
                    SELECT id, user_id, title, created_at, updated_at
                    FROM conversations
                    WHERE user_id = $1
                    ORDER BY updated_at {sort_order}
                    OFFSET $2
                    """,
                    user_id,
                    offset,
                )
        return [self._row_to_conversation(r) for r in rows]

    async def get_conversation(self, user_id: str, conversation_id: str) -> dict | None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, user_id, title, created_at, updated_at
                FROM conversations
                WHERE id = $1 AND user_id = $2
                """,
                conversation_id,
                user_id,
            )
        if row is None:
            return None
        return self._row_to_conversation(row)

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def create_message(
        self,
        uuid: str,
        conversation_id: str,
        user_id: str,
        input_message: dict,
    ) -> dict | str:
        import json as _json

        pool = await self._get_pool()
        now = datetime.now(timezone.utc)

        # Check the conversation exists
        async with pool.acquire() as conn:
            conv_exists = await conn.fetchval(
                "SELECT id FROM conversations WHERE id = $1 AND user_id = $2",
                conversation_id,
                user_id,
            )
            if not conv_exists:
                return "Conversation not found"

            content_value = _json.dumps(input_message)
            feedback_value = "" if self.enable_message_feedback else None

            row = await conn.fetchrow(
                """
                INSERT INTO messages
                    (id, conversation_id, user_id, role, content, feedback, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $7)
                ON CONFLICT (id) DO UPDATE
                    SET content   = EXCLUDED.content,
                        role      = EXCLUDED.role,
                        updated_at = EXCLUDED.updated_at
                RETURNING id, conversation_id, user_id, role, content, feedback, created_at, updated_at
                """,
                uuid,
                conversation_id,
                user_id,
                input_message.get("role", ""),
                content_value,
                feedback_value,
                now,
            )

            # Update conversation's updated_at
            await conn.execute(
                "UPDATE conversations SET updated_at = $1 WHERE id = $2",
                now,
                conversation_id,
            )

        return self._row_to_message(row)

    async def update_message_feedback(
        self, user_id: str, message_id: str, feedback: str
    ) -> dict | None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE messages
                SET feedback = $1, updated_at = now()
                WHERE id = $2 AND user_id = $3
                RETURNING id, conversation_id, user_id, role, content, feedback, created_at, updated_at
                """,
                feedback,
                message_id,
                user_id,
            )
        if row is None:
            return None
        return self._row_to_message(row)

    async def get_messages(self, user_id: str, conversation_id: str) -> list:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, conversation_id, user_id, role, content, feedback, created_at, updated_at
                FROM messages
                WHERE conversation_id = $1 AND user_id = $2
                ORDER BY created_at ASC
                """,
                conversation_id,
                user_id,
            )
        return [self._row_to_message(r) for r in rows]

    async def delete_messages(self, conversation_id: str, user_id: str):
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM messages WHERE conversation_id = $1 AND user_id = $2",
                conversation_id,
                user_id,
            )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _parse_dt(value) -> datetime | None:
    """Try to parse an ISO-8601 string or return a datetime unchanged."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
