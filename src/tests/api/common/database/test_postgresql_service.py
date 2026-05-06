"""Unit tests for PostgreSQLConversationClient."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from common.database.postgresql_service import PostgreSQLConversationClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(data: dict):
    """Build a simple object that behaves like an asyncpg Record."""
    class _Row:
        def __init__(self, d):
            self._d = d

        def __getitem__(self, key):
            return self._d[key]

        def __contains__(self, key):
            return key in self._d

    return _Row(data)


def _now():
    return datetime.now(timezone.utc)


def _conv_row(conv_id="conv-1", user_id="user-1", title="Test"):
    return _make_row({
        "id": conv_id,
        "user_id": user_id,
        "title": title,
        "created_at": _now(),
        "updated_at": _now(),
    })


def _msg_row(msg_id="msg-1", conv_id="conv-1", user_id="user-1",
             role="user", content=None, feedback=None):
    return _make_row({
        "id": msg_id,
        "conversation_id": conv_id,
        "user_id": user_id,
        "role": role,
        "content": content or {"role": role, "content": "Hello"},
        "feedback": feedback,
        "created_at": _now(),
        "updated_at": _now(),
    })


@pytest.fixture
def pg_client():
    """Return a PostgreSQLConversationClient with a mocked connection pool."""
    client = PostgreSQLConversationClient(
        host="localhost",
        port=5432,
        database="testdb",
        user="testuser",
        password="testpass",
        enable_message_feedback=True,
    )
    return client


@pytest.fixture
def mock_pool():
    """Return a MagicMock that acts as an asyncpg pool."""
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPostgreSQLConversationClientInit:
    def test_attributes_stored(self):
        client = PostgreSQLConversationClient(
            host="pg-host",
            port=5433,
            database="mydb",
            user="alice",
            password="secret",
            enable_message_feedback=True,
        )
        assert client.host == "pg-host"
        assert client.port == 5433
        assert client.database == "mydb"
        assert client.user == "alice"
        assert client.password == "secret"
        assert client.enable_message_feedback is True

    def test_cosmosdb_client_shim_points_to_self(self):
        client = PostgreSQLConversationClient(
            host="h", port=5432, database="d", user="u", password="p"
        )
        assert client.cosmosdb_client is client


class TestPostgreSQLEnsure:
    @pytest.mark.asyncio
    async def test_ensure_success(self, pg_client, mock_pool):
        pool, conn = mock_pool
        conn.execute = AsyncMock()
        with patch.object(pg_client, "_get_pool", AsyncMock(return_value=pool)):
            success, msg = await pg_client.ensure()
        assert success is True
        assert "successfully" in msg

    @pytest.mark.asyncio
    async def test_ensure_failure(self, pg_client):
        with patch.object(
            pg_client, "_get_pool", AsyncMock(side_effect=Exception("connection refused"))
        ):
            success, msg = await pg_client.ensure()
        assert success is False
        assert "connection refused" in msg


class TestPostgreSQLConversations:
    @pytest.mark.asyncio
    async def test_create_conversation(self, pg_client, mock_pool):
        pool, conn = mock_pool
        conv_id = "test-conv-id"
        row = _conv_row(conv_id=conv_id)
        conn.fetchrow = AsyncMock(return_value=row)

        with patch.object(pg_client, "_get_pool", AsyncMock(return_value=pool)):
            result = await pg_client.create_conversation(
                user_id="user-1", conversation_id=conv_id, title="My Convo"
            )

        assert result["id"] == conv_id
        assert result["type"] == "conversation"
        assert result["userId"] == "user-1"
        assert result["title"] == "Test"

    @pytest.mark.asyncio
    async def test_create_conversation_generates_uuid_if_none(self, pg_client, mock_pool):
        pool, conn = mock_pool
        row = _conv_row()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch.object(pg_client, "_get_pool", AsyncMock(return_value=pool)):
            result = await pg_client.create_conversation(user_id="user-1")

        assert result["id"] is not None

    @pytest.mark.asyncio
    async def test_upsert_conversation(self, pg_client, mock_pool):
        pool, conn = mock_pool
        row = _conv_row(conv_id="conv-1", title="Updated Title")
        conn.fetchrow = AsyncMock(return_value=row)

        conv = {
            "id": "conv-1",
            "userId": "user-1",
            "title": "Updated Title",
            "createdAt": _now().isoformat(),
        }
        with patch.object(pg_client, "_get_pool", AsyncMock(return_value=pool)):
            result = await pg_client.upsert_conversation(conv)

        assert result["id"] == "conv-1"
        assert result["title"] == "Updated Title"

    @pytest.mark.asyncio
    async def test_delete_conversation(self, pg_client, mock_pool):
        pool, conn = mock_pool
        conn.execute = AsyncMock()

        with patch.object(pg_client, "_get_pool", AsyncMock(return_value=pool)):
            await pg_client.delete_conversation("user-1", "conv-1")

        conn.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_conversation_found(self, pg_client, mock_pool):
        pool, conn = mock_pool
        row = _conv_row(conv_id="conv-1")
        conn.fetchrow = AsyncMock(return_value=row)

        with patch.object(pg_client, "_get_pool", AsyncMock(return_value=pool)):
            result = await pg_client.get_conversation("user-1", "conv-1")

        assert result is not None
        assert result["id"] == "conv-1"

    @pytest.mark.asyncio
    async def test_get_conversation_not_found(self, pg_client, mock_pool):
        pool, conn = mock_pool
        conn.fetchrow = AsyncMock(return_value=None)

        with patch.object(pg_client, "_get_pool", AsyncMock(return_value=pool)):
            result = await pg_client.get_conversation("user-1", "nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_conversations_with_limit(self, pg_client, mock_pool):
        pool, conn = mock_pool
        conn.fetch = AsyncMock(return_value=[_conv_row("c1"), _conv_row("c2")])

        with patch.object(pg_client, "_get_pool", AsyncMock(return_value=pool)):
            results = await pg_client.get_conversations("user-1", limit=10, offset=0)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_get_conversations_no_limit(self, pg_client, mock_pool):
        pool, conn = mock_pool
        conn.fetch = AsyncMock(return_value=[_conv_row()])

        with patch.object(pg_client, "_get_pool", AsyncMock(return_value=pool)):
            results = await pg_client.get_conversations("user-1")

        assert len(results) == 1


class TestPostgreSQLMessages:
    @pytest.mark.asyncio
    async def test_create_message_success(self, pg_client, mock_pool):
        pool, conn = mock_pool
        # conv_exists check
        conn.fetchval = AsyncMock(return_value="conv-1")
        row = _msg_row()
        conn.fetchrow = AsyncMock(return_value=row)
        conn.execute = AsyncMock()

        input_message = {"role": "user", "content": "Hello"}
        with patch.object(pg_client, "_get_pool", AsyncMock(return_value=pool)):
            result = await pg_client.create_message(
                uuid="msg-uuid",
                conversation_id="conv-1",
                user_id="user-1",
                input_message=input_message,
            )

        assert result["id"] == "msg-1"
        assert result["role"] == "user"

    @pytest.mark.asyncio
    async def test_create_message_conversation_not_found(self, pg_client, mock_pool):
        pool, conn = mock_pool
        conn.fetchval = AsyncMock(return_value=None)

        input_message = {"role": "user", "content": "Hello"}
        with patch.object(pg_client, "_get_pool", AsyncMock(return_value=pool)):
            result = await pg_client.create_message(
                uuid="msg-uuid",
                conversation_id="nonexistent",
                user_id="user-1",
                input_message=input_message,
            )

        assert result == "Conversation not found"

    @pytest.mark.asyncio
    async def test_create_message_feedback_enabled(self, pg_client, mock_pool):
        """When feedback is enabled the INSERT should include an empty feedback field."""
        pool, conn = mock_pool
        conn.fetchval = AsyncMock(return_value="conv-1")
        row = _msg_row(feedback="")
        conn.fetchrow = AsyncMock(return_value=row)
        conn.execute = AsyncMock()

        pg_client.enable_message_feedback = True
        input_message = {"role": "user", "content": "Hi"}
        with patch.object(pg_client, "_get_pool", AsyncMock(return_value=pool)):
            result = await pg_client.create_message(
                uuid="msg-1",
                conversation_id="conv-1",
                user_id="user-1",
                input_message=input_message,
            )

        assert result["feedback"] == ""

    @pytest.mark.asyncio
    async def test_update_message_feedback(self, pg_client, mock_pool):
        pool, conn = mock_pool
        row = _msg_row(feedback="thumbs_up")
        conn.fetchrow = AsyncMock(return_value=row)

        with patch.object(pg_client, "_get_pool", AsyncMock(return_value=pool)):
            result = await pg_client.update_message_feedback("user-1", "msg-1", "thumbs_up")

        assert result is not None
        assert result["feedback"] == "thumbs_up"

    @pytest.mark.asyncio
    async def test_update_message_feedback_not_found(self, pg_client, mock_pool):
        pool, conn = mock_pool
        conn.fetchrow = AsyncMock(return_value=None)

        with patch.object(pg_client, "_get_pool", AsyncMock(return_value=pool)):
            result = await pg_client.update_message_feedback("user-1", "nonexistent", "thumbs_up")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_messages(self, pg_client, mock_pool):
        pool, conn = mock_pool
        conn.fetch = AsyncMock(return_value=[_msg_row("m1"), _msg_row("m2")])

        with patch.object(pg_client, "_get_pool", AsyncMock(return_value=pool)):
            results = await pg_client.get_messages("user-1", "conv-1")

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_delete_messages(self, pg_client, mock_pool):
        pool, conn = mock_pool
        conn.execute = AsyncMock()

        with patch.object(pg_client, "_get_pool", AsyncMock(return_value=pool)):
            await pg_client.delete_messages("conv-1", "user-1")

        conn.execute.assert_awaited_once()


class TestPostgreSQLClose:
    @pytest.mark.asyncio
    async def test_close_releases_pool(self, pg_client, mock_pool):
        pool, _ = mock_pool
        pool.close = AsyncMock()
        pg_client._pool = pool

        await pg_client.close()

        pool.close.assert_awaited_once()
        assert pg_client._pool is None

    @pytest.mark.asyncio
    async def test_close_noop_when_no_pool(self, pg_client):
        """close() should not raise if pool was never created."""
        await pg_client.close()
