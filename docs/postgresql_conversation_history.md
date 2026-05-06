# PostgreSQL conversation history

By default, conversation history is stored in **Azure Cosmos DB**.  
Setting `CHAT_HISTORY_BACKEND=postgresql` switches the persistence layer to a PostgreSQL database you manage.

---

## Prerequisites

- A PostgreSQL 13+ server reachable from the API container.
- A database and a user/role with `CREATE TABLE`, `INSERT`, `UPDATE`, `DELETE`, `SELECT` privileges on that database.

---

## Environment variables

Add the following variables to your `.env` file (or Azure App Service Application Settings):

| Variable | Required | Default | Description |
|---|---|---|---|
| `CHAT_HISTORY_BACKEND` | No | `cosmosdb` | Set to `postgresql` to enable the PostgreSQL backend |
| `POSTGRESQL_HOST` | Yes (when pg) | — | Hostname or IP of the PostgreSQL server |
| `POSTGRESQL_PORT` | No | `5432` | TCP port |
| `POSTGRESQL_DATABASE` | Yes (when pg) | — | Target database name |
| `POSTGRESQL_USER` | Yes (when pg) | — | Login role |
| `POSTGRESQL_PASSWORD` | Yes (when pg) | — | Password for the login role |
| `POSTGRESQL_ENABLE_FEEDBACK` | No | `False` | Store per-message thumbs-up/down feedback |
| `USE_CHAT_HISTORY_ENABLED` | No | `false` | Must still be `true` for any history to be stored |

Example `.env` fragment:

```env
USE_CHAT_HISTORY_ENABLED=True
CHAT_HISTORY_BACKEND=postgresql
POSTGRESQL_HOST=my-pg-server.postgres.database.azure.com
POSTGRESQL_PORT=5432
POSTGRESQL_DATABASE=conversations
POSTGRESQL_USER=appuser
POSTGRESQL_PASSWORD=<your-password>
POSTGRESQL_ENABLE_FEEDBACK=True
```

---

## Schema

The schema is created **automatically** the first time the application calls the `/history/ensure` endpoint (or any other history endpoint). No manual migration step is needed.

Two tables are created inside the target database:

### `conversations`

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT` | Primary key (UUID string) |
| `user_id` | `TEXT` | Azure AD principal ID of the owner |
| `title` | `TEXT` | Auto-generated title for the conversation |
| `created_at` | `TIMESTAMPTZ` | Creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | Timestamp of the last message |

### `messages`

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT` | Primary key (UUID string) |
| `conversation_id` | `TEXT` | Foreign key → `conversations.id` (CASCADE DELETE) |
| `user_id` | `TEXT` | Owner |
| `role` | `TEXT` | `user`, `assistant`, or `tool` |
| `content` | `JSONB` | Full message object |
| `feedback` | `TEXT` | `thumbs_up` / `thumbs_down` / `null` |
| `created_at` | `TIMESTAMPTZ` | Creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | Last update timestamp |

---

## Azure Database for PostgreSQL (Flexible Server)

If you are using [Azure Database for PostgreSQL – Flexible Server](https://learn.microsoft.com/azure/postgresql/flexible-server/overview) you can use a managed identity instead of a password.  
In that case, set `POSTGRESQL_USER` to the managed identity's database login and leave `POSTGRESQL_PASSWORD` empty; provide the token externally or adjust the connection logic in `postgresql_service.py` to use Azure token authentication.

---

## Backward compatibility

- Existing deployments using Cosmos DB are **not affected**. The `CHAT_HISTORY_BACKEND` variable defaults to `cosmosdb`.
- If `CHAT_HISTORY_BACKEND=postgresql` is set but any required PostgreSQL variable is missing, the service logs a warning and falls back to Cosmos DB.
