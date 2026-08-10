"""
Advanced MongoDB -> MongoDB clone manager for the bot.

Install as: plugins/clone.py

Features:
- /clonemenu (admins only)
- Multiple saved source MongoDB URLs
- Source collection discovery with inline buttons
- Direct MongoDB-to-MongoDB transfer (no Telegram download/re-upload)
- Bulk upserts in batches
- Automatic destination selection between Media and Media2
- Duplicate-safe cloning
- Progress, statistics and cancel button
- Source add/delete/run management

This plugin intentionally writes the same document shape used by ia_filterdb.py.
It does NOT call save_file(), because cloned records already contain the encoded
_id/file_id and file_ref produced by the source bot.
"""

import asyncio
import time
from datetime import datetime
from urllib.parse import urlparse

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne
from pymongo.errors import OperationFailure, BulkWriteError

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS, DATABASE_URI, DATABASE_NAME, COLLECTION_NAME, MULTIPLE_DB, DB_CHANGE_LIMIT
from database.ia_filterdb import Media, Media2, check_db_size
from logging_helper import LOGGER


# ---------------------------------------------------------------------------
# Target database used only for clone configuration/progress metadata.
# ---------------------------------------------------------------------------
_target_client = AsyncIOMotorClient(DATABASE_URI)
_target_db = _target_client[DATABASE_NAME]
_sources_col = _target_db["clone_sources"]


# One active clone at a time. This prevents two huge transfers from competing
# for the same target quota and MongoDB connection pool.
_clone_lock = asyncio.Lock()
_clone_task = None
_clone_cancel = False

# Conversation state for /clonemenu -> Add Source -> URL.
_pending_url = {}

BATCH_SIZE = 2000
PROGRESS_EVERY = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_admin(user_id: int) -> bool:
    return user_id in ADMINS


def _oid(value):
    try:
        return ObjectId(str(value))
    except Exception:
        return None


def _source_label(doc):
    return doc.get("name") or f"Source {str(doc['_id'])[-5:]}"


def _mask_mongo_url(uri: str) -> str:
    """Hide username/password while displaying a source."""
    try:
        parsed = urlparse(uri)
        if parsed.username is None:
            return uri
        host = parsed.hostname or "host"
        port = f":{parsed.port}" if parsed.port else ""
        return f"mongodb{'s' if parsed.scheme.endswith('+srv') else ''}://***:***@{host}{port}/..."
    except Exception:
        return "mongodb://***:***@..."


def _source_db_name(uri: str):
    """Return database encoded in the URI, if one exists."""
    try:
        parsed = urlparse(uri)
        path = (parsed.path or "").strip("/")
        return path or None
    except Exception:
        return None


def _quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(x in text for x in (
        "space quota",
        "quota exceeded",
        "over your space quota",
        "storage quota",
        "exceeded the space",
        "not enough space",
    ))


def _clean_document(doc):
    """Map a source bot Media document to the exact target schema.

    Source bot records normally have `_id` as the encoded file id because
    ia_filterdb.Media defines file_id with attribute='_id'. Some Mongo exports
    may additionally contain a `file_id` field, so both are supported.
    """
    raw_id = doc.get("_id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        raw_id = doc.get("file_id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        return None, "missing/invalid file_id"

    file_name = doc.get("file_name")
    if not isinstance(file_name, str) or not file_name.strip():
        return None, "missing file_name"

    try:
        file_size = int(doc.get("file_size", 0) or 0)
    except Exception:
        return None, "invalid file_size"

    result = {
        "_id": raw_id,
        "file_ref": doc.get("file_ref"),
        "file_name": file_name,
        "file_size": file_size,
        "file_type": doc.get("file_type"),
        "mime_type": doc.get("mime_type"),
        "caption": doc.get("caption"),
    }
    return result, None


async def _get_source(source_id):
    return await _sources_col.find_one({"_id": _oid(source_id)})


async def _list_sources():
    return await _sources_col.find({}).sort("created_at", 1).to_list(length=100)


async def _source_client(source):
    uri = source["uri"]
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=10000, connectTimeoutMS=10000)
    await client.admin.command("ping")
    db_name = source.get("database") or _source_db_name(uri)
    if not db_name:
        client.close()
        raise ValueError("Database name is missing from the MongoDB URL. Use a URL containing /database.")
    return client, client[db_name]


async def _destination_collection():
    """Choose Media or Media2 according to the current primary quota."""
    if not MULTIPLE_DB:
        return Media.collection, "Primary"

    size = await check_db_size(Media.collection.database)
    limit = int(DB_CHANGE_LIMIT) * 1024 * 1024
    if size >= limit:
        return Media2.collection, "Secondary"
    return Media.collection, "Primary"


async def _bulk_clone_batch(target_collection, documents):
    """Insert only missing ids using bulk upsert."""
    if not documents:
        return 0, 0

    operations = [
        UpdateOne(
            {"_id": doc["_id"]},
            {"$setOnInsert": doc},
            upsert=True,
        )
        for doc in documents
    ]

    try:
        result = await target_collection.bulk_write(operations, ordered=False)
        return result.upserted_count, len(documents) - result.upserted_count
    except BulkWriteError as exc:
        # Unordered writes can contain successful operations even when some
        # documents fail. Count what MongoDB reports as inserted.
        details = exc.details or {}
        inserted = int(details.get("nUpserted", 0) or 0)
        write_errors = details.get("writeErrors", []) or []
        failed = len(write_errors)
        existing_or_failed = max(0, len(documents) - inserted)
        if any(_quota_error(e.get("errmsg", "")) for e in write_errors):
            raise OperationFailure(str(exc))
        return inserted, existing_or_failed


async def _clone_source(source, message):
    global _clone_cancel
    _clone_cancel = False

    client = None
    started = time.time()
    stats = {
        "read": 0,
        "saved": 0,
        "existing": 0,
        "invalid": 0,
        "errors": 0,
        "batches": 0,
        "target": "Primary",
    }

    try:
        client, source_db = await _source_client(source)
        source_collection = source_db[source["collection"]]

        total = await source_collection.estimated_document_count()
        source_name = _source_label(source)

        await message.edit_text(
            f"🚀 <b>Clone Started</b>\n\n"
            f"🗄 Source: <code>{source_name}</code>\n"
            f"📁 Collection: <code>{source['collection']}</code>\n"
            f"📦 Source documents: <code>{total:,}</code>\n\n"
            f"⏳ Reading MongoDB directly...",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⛔ Cancel Clone", callback_data="clone:cancel")],
                [InlineKeyboardButton("✖ Close", callback_data="clone:close")],
            ]),
        )

        cursor = source_collection.find({}, no_cursor_timeout=True).batch_size(BATCH_SIZE)
        batch = []
        last_update = time.time()

        try:
            async for raw in cursor:
                if _clone_cancel:
                    break

                stats["read"] += 1
                cleaned, error = _clean_document(raw)
                if error:
                    stats["invalid"] += 1
                    continue
                batch.append(cleaned)

                if len(batch) >= BATCH_SIZE:
                    inserted, existing = await _write_clone_batch(batch, stats)
                    stats["saved"] += inserted
                    stats["existing"] += existing
                    stats["batches"] += 1
                    batch.clear()

                    if time.time() - last_update >= PROGRESS_EVERY:
                        await _update_progress(message, source_name, total, stats, started)
                        last_update = time.time()

            if batch and not _clone_cancel:
                inserted, existing = await _write_clone_batch(batch, stats)
                stats["saved"] += inserted
                stats["existing"] += existing
                stats["batches"] += 1
        finally:
            await cursor.close()

        elapsed = time.time() - started
        if _clone_cancel:
            title = "⛔ <b>Clone Cancelled</b>"
        else:
            title = "✅ <b>Clone Completed</b>"

        rate = stats["saved"] / elapsed if elapsed else 0
        await message.edit_text(
            f"{title}\n\n"
            f"🗄 Source: <code>{source_name}</code>\n"
            f"📁 Collection: <code>{source['collection']}</code>\n\n"
            f"📥 Read: <code>{stats['read']:,}</code>\n"
            f"💾 New files: <code>{stats['saved']:,}</code>\n"
            f"🔁 Already existed: <code>{stats['existing']:,}</code>\n"
            f"⚠️ Invalid: <code>{stats['invalid']:,}</code>\n"
            f"❌ Errors: <code>{stats['errors']:,}</code>\n"
            f"🎯 Last target: <code>{stats['target']}</code>\n"
            f"⏱ Time: <code>{_duration(elapsed)}</code>\n"
            f"⚡ New files/sec: <code>{rate:,.1f}</code>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Clone Again", callback_data=f"clone:run:{source['_id']}")],
                [InlineKeyboardButton("📋 Sources", callback_data="clone:sources")],
                [InlineKeyboardButton("✖ Close", callback_data="clone:close")],
            ]),
        )

    except Exception as exc:
        LOGGER.exception("Clone failed")
        stats["errors"] += 1
        try:
            await message.edit_text(
                f"❌ <b>Clone Failed</b>\n\n"
                f"<code>{str(exc)[:2500]}</code>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Sources", callback_data="clone:sources")],
                    [InlineKeyboardButton("✖ Close", callback_data="clone:close")],
                ]),
            )
        except Exception:
            pass
    finally:
        if client:
            client.close()


async def _write_clone_batch(batch, stats):
    """Write a batch, moving to DB2 if DB1 is full."""
    target, target_name = await _destination_collection()
    stats["target"] = target_name

    try:
        return await _bulk_clone_batch(target, batch)
    except OperationFailure as exc:
        if not MULTIPLE_DB or target_name != "Primary" or not _quota_error(exc):
            raise

        LOGGER.warning("Primary quota reached during clone; switching batch to Media2")
        stats["target"] = "Secondary"
        return await _bulk_clone_batch(Media2.collection, batch)


async def _update_progress(message, source_name, total, stats, started):
    elapsed = time.time() - started
    percent = (stats["read"] / total * 100) if total else 0
    rate = stats["saved"] / elapsed if elapsed else 0
    await message.edit_text(
        f"🚀 <b>Cloning...</b>\n\n"
        f"🗄 Source: <code>{source_name}</code>\n"
        f"📊 Progress: <code>{percent:.1f}%</code>\n"
        f"📥 Read: <code>{stats['read']:,}/{total:,}</code>\n"
        f"💾 New: <code>{stats['saved']:,}</code>\n"
        f"🔁 Existing: <code>{stats['existing']:,}</code>\n"
        f"⚠️ Invalid: <code>{stats['invalid']:,}</code>\n"
        f"🎯 Target: <code>{stats['target']}</code>\n"
        f"⚡ Speed: <code>{rate:,.1f} new/sec</code>\n"
        f"⏱ Elapsed: <code>{_duration(elapsed)}</code>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⛔ Cancel Clone", callback_data="clone:cancel")],
            [InlineKeyboardButton("✖ Close", callback_data="clone:close")],
        ]),
    )


def _duration(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


async def _menu_text():
    sources = await _list_sources()
    total = len(sources)
    running = _clone_lock.locked()
    return (
        "⚡ <b>MongoDB Clone Manager</b>\n\n"
        f"🔗 Sources: <code>{total}</code>\n"
        f"🚀 Status: <code>{'CLONING' if running else 'IDLE'}</code>\n"
        f"🎯 Target: <code>{COLLECTION_NAME}</code>"
    )


def _menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Source", callback_data="clone:add"),
         InlineKeyboardButton("📋 Sources", callback_data="clone:sources")],
        [InlineKeyboardButton("📊 Target Stats", callback_data="clone:stats"),
         InlineKeyboardButton("⛔ Stop Clone", callback_data="clone:cancel")],
        [InlineKeyboardButton("✖ Close", callback_data="clone:close")],
    ])


@Client.on_message(filters.command("clonemenu") & filters.user(ADMINS))
async def clone_menu(bot, message):
    await message.reply_text(await _menu_text(), reply_markup=_menu_keyboard())


@Client.on_message(filters.private & filters.incoming & filters.text & filters.user(ADMINS))
async def clone_url_receiver(bot, message):
    user_id = message.from_user.id
    if user_id not in _pending_url:
        return

    # Do not consume ordinary bot commands while waiting for a URL.
    if message.text.startswith("/"):
        return

    url = message.text.strip()
    if not url.startswith("mongodb://") and not url.startswith("mongodb+srv://"):
        return await message.reply_text("❌ Send a valid MongoDB URL starting with mongodb:// or mongodb+srv://")

    status = await message.reply_text("🔌 Connecting to source MongoDB...")
    client = None
    try:
        client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=10000, connectTimeoutMS=10000)
        await client.admin.command("ping")
        db_name = _source_db_name(url)
        if not db_name:
            client.close()
            _pending_url.pop(user_id, None)
            return await status.edit_text(
                "❌ This MongoDB URL does not contain a database name.\n\n"
                "Use a URL like:\n<code>mongodb+srv://user:pass@cluster.mongodb.net/DatabaseName</code>"
            )

        db = client[db_name]
        collections = await db.list_collection_names()
        # Do not offer MongoDB/system collections as clone targets.
        collections = [c for c in collections if not c.startswith("system.")]
        _pending_url[user_id] = {"url": url, "database": db_name, "collections": collections}

        if not collections:
            return await status.edit_text("❌ No usable collections were found in that database.")

        rows = []
        for i in range(0, len(collections), 2):
            row = [InlineKeyboardButton(collections[i][:28], callback_data=f"clone:pick:{i}")]
            if i + 1 < len(collections):
                row.append(InlineKeyboardButton(collections[i + 1][:28], callback_data=f"clone:pick:{i+1}"))
            rows.append(row)
        rows.append([InlineKeyboardButton("✖ Cancel", callback_data="clone:canceladd")])

        await status.edit_text(
            "📁 <b>Select Source Collection</b>\n\n"
            f"Database: <code>{db_name}</code>\n"
            f"Collections: <code>{len(collections)}</code>",
            reply_markup=InlineKeyboardMarkup(rows),
        )
    except Exception as exc:
        if client:
            client.close()
        await status.edit_text(f"❌ Could not connect to source MongoDB:\n<code>{str(exc)[:2000]}</code>")


@Client.on_callback_query(filters.regex(r"^clone:"))
async def clone_callbacks(bot, query):
    global _clone_task, _clone_cancel

    if not _is_admin(query.from_user.id):
        return await query.answer("Not allowed.", show_alert=True)

    data = query.data.split(":")
    action = data[1] if len(data) > 1 else ""

    if action == "close":
        try:
            await query.message.delete()
        except Exception:
            await query.message.edit_text("Closed.")
        return await query.answer()

    if action == "cancel":
        _clone_cancel = True
        if _clone_task and not _clone_task.done():
            await query.answer("Cancellation requested. Finishing the current batch...", show_alert=True)
        else:
            await query.answer("No clone is running.", show_alert=True)
        return

    if action == "canceladd":
        _pending_url.pop(query.from_user.id, None)
        return await query.message.edit_text(await _menu_text(), reply_markup=_menu_keyboard())

    if action == "add":
        if _clone_lock.locked():
            return await query.answer("A clone is currently running.", show_alert=True)
        _pending_url[query.from_user.id] = {"waiting": True}
        await query.message.edit_text(
            "➕ <b>Add MongoDB Source</b>\n\n"
            "Send the <b>source MongoDB URL</b>.\n\n"
            "The URL should include the source database name, for example:\n"
            "<code>mongodb+srv://user:password@cluster.mongodb.net/DatabaseName</code>\n\n"
            "🔒 The URL is stored only in your bot's MongoDB clone configuration.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✖ Cancel", callback_data="clone:canceladd")]
            ]),
        )
        return await query.answer()

    if action == "pick":
        state = _pending_url.get(query.from_user.id)
        if not state or "url" not in state:
            return await query.answer("Source setup expired. Press Add Source again.", show_alert=True)
        try:
            index = int(data[2])
            collection = state["collections"][index]
        except Exception:
            return await query.answer("Invalid collection.", show_alert=True)

        doc = {
            "name": f"Source {int(time.time())}",
            "uri": state["url"],
            "database": state["database"],
            "collection": collection,
            "created_at": datetime.utcnow(),
        }
        result = await _sources_col.insert_one(doc)
        _pending_url.pop(query.from_user.id, None)

        await query.message.edit_text(
            "✅ <b>Source Added</b>\n\n"
            f"📁 Collection: <code>{collection}</code>\n"
            f"🗄 Database: <code>{state['database']}</code>\n"
            f"🔗 Source ID: <code>{str(result.inserted_id)[-6:]}</code>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 Clone Now", callback_data=f"clone:run:{result.inserted_id}")],
                [InlineKeyboardButton("📋 Sources", callback_data="clone:sources")],
                [InlineKeyboardButton("🔙 Menu", callback_data="clone:menu")],
            ]),
        )
        return await query.answer("Source saved.")

    if action == "menu":
        return await query.message.edit_text(await _menu_text(), reply_markup=_menu_keyboard())

    if action == "sources":
        sources = await _list_sources()
        rows = []
        for source in sources:
            sid = str(source["_id"])
            label = f"🗄 {_source_label(source)} • {source['collection']}"
            rows.append([InlineKeyboardButton(label[:60], callback_data=f"clone:source:{sid}")])
        rows.append([InlineKeyboardButton("➕ Add Source", callback_data="clone:add")])
        rows.append([InlineKeyboardButton("🔙 Menu", callback_data="clone:menu")])
        text = "📋 <b>Saved MongoDB Sources</b>\n\n"
        text += "No sources saved." if not sources else "Select a source:"
        return await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(rows))

    if action == "source":
        source = await _get_source(data[2] if len(data) > 2 else "")
        if not source:
            return await query.answer("Source not found.", show_alert=True)
        count = "?"
        try:
            client, db = await _source_client(source)
            count = f"{await db[source['collection']].estimated_document_count():,}"
            client.close()
        except Exception:
            pass

        sid = str(source["_id"])
        return await query.message.edit_text(
            f"🗄 <b>{_source_label(source)}</b>\n\n"
            f"📁 Collection: <code>{source['collection']}</code>\n"
            f"🗃 Database: <code>{source['database']}</code>\n"
            f"📦 Documents: <code>{count}</code>\n"
            f"🔗 URL: <code>{_mask_mongo_url(source['uri'])}</code>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 Start Clone", callback_data=f"clone:run:{sid}")],
                [InlineKeyboardButton("🗑 Delete Source", callback_data=f"clone:delete:{sid}")],
                [InlineKeyboardButton("🔙 Sources", callback_data="clone:sources")],
            ]),
        )

    if action == "delete":
        source = await _get_source(data[2] if len(data) > 2 else "")
        if not source:
            return await query.answer("Source not found.", show_alert=True)
        await _sources_col.delete_one({"_id": source["_id"]})
        return await query.message.edit_text(await _menu_text(), reply_markup=_menu_keyboard())

    if action == "stats":
        try:
            size1 = await check_db_size(Media.collection.database)
            text = f"📊 <b>Target Database</b>\n\nPrimary data size: <code>{size1 / 1024 / 1024:.1f} MB</code>\nLimit: <code>{DB_CHANGE_LIMIT} MB</code>"
            if MULTIPLE_DB:
                try:
                    stats2 = await Media2.collection.database.command("dbstats")
                    size2 = stats2.get("dataSize", 0)
                    text += f"\nSecondary data size: <code>{size2 / 1024 / 1024:.1f} MB</code>"
                except Exception:
                    pass
            text += f"\n\nMedia: <code>{await Media.count_documents({}):,}</code>\nMedia2: <code>{await Media2.count_documents({}):,}</code>"
        except Exception as exc:
            text = f"❌ Stats error: <code>{str(exc)[:1000]}</code>"
        return await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="clone:stats")],
            [InlineKeyboardButton("🔙 Menu", callback_data="clone:menu")],
        ]))

    if action == "run":
        if len(data) < 3:
            return await query.answer("Invalid source.", show_alert=True)
        source = await _get_source(data[2])
        if not source:
            return await query.answer("Source not found.", show_alert=True)
        if _clone_lock.locked():
            return await query.answer("Another clone is already running.", show_alert=True)

        await query.answer("Clone started.")
        async with _clone_lock:
            _clone_task = asyncio.current_task()
            await _clone_source(source, query.message)
            _clone_task = None
        return

    await query.answer()
