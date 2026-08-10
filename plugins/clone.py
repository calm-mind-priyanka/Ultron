"""
Advanced MongoDB -> MongoDB clone manager for the bot.

Install as: plugins/clone.py

Flow:
- /clonemenu (admins only)
- Add Source -> MongoDB URL -> Database Name -> Collection Name
- Multiple saved sources
- Every submenu has a Back button
- Direct MongoDB-to-MongoDB transfer (no Telegram download/re-upload)
- Bulk upserts in batches
- Automatic destination selection between Media and Media2
- Duplicate-safe cloning
- Progress / cancel / pause / resume
- Target statistics
- Only the selected source collection is cloned
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


_target_client = AsyncIOMotorClient(DATABASE_URI)
_target_db = _target_client[DATABASE_NAME]
_sources_col = _target_db["clone_sources"]

_clone_lock = asyncio.Lock()
_clone_task = None
_clone_cancel = False
_clone_paused = False

_pending_add = {}

BATCH_SIZE = 2000
PROGRESS_EVERY = 5


def _is_admin(user_id):
    return user_id in ADMINS


def _oid(value):
    try:
        return ObjectId(str(value))
    except Exception:
        return None


def _source_label(doc):
    return doc.get("name") or f"Source {str(doc['_id'])[-5:]}"


def _mask_mongo_url(uri):
    try:
        parsed = urlparse(uri)
        if parsed.username is None:
            return uri
        host = parsed.hostname or "host"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://***:***@{host}{port}/..."
    except Exception:
        return "mongodb://***:***@..."


def _quota_error(exc):
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

    return {
        "_id": raw_id,
        "file_ref": doc.get("file_ref"),
        "file_name": file_name,
        "file_size": file_size,
        "file_type": doc.get("file_type"),
        "mime_type": doc.get("mime_type"),
        "caption": doc.get("caption"),
    }, None


async def _get_source(source_id):
    oid = _oid(source_id)
    if not oid:
        return None
    return await _sources_col.find_one({"_id": oid})


async def _list_sources():
    return await _sources_col.find({}).sort("created_at", 1).to_list(length=100)


async def _source_client(source):
    client = AsyncIOMotorClient(
        source["uri"],
        serverSelectionTimeoutMS=10000,
        connectTimeoutMS=10000,
    )
    await client.admin.command("ping")

    db_name = source.get("database")
    if not db_name:
        client.close()
        raise ValueError("Source database name is missing.")

    return client, client[db_name]


async def _destination_collection():
    if not MULTIPLE_DB:
        return Media.collection, "Primary"

    size = await check_db_size(Media.collection.database)
    limit = int(DB_CHANGE_LIMIT) * 1024 * 1024

    if size >= limit:
        return Media2.collection, "Secondary"

    return Media.collection, "Primary"


async def _bulk_clone_batch(target_collection, documents):
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
        result = await target_collection.bulk_write(
            operations,
            ordered=False,
        )
        inserted = int(result.upserted_count or 0)
        existing = max(0, len(documents) - inserted)
        return inserted, existing

    except BulkWriteError as exc:
        details = exc.details or {}
        inserted = int(details.get("nUpserted", 0) or 0)
        errors = details.get("writeErrors", []) or []

        if any(_quota_error(e.get("errmsg", "")) for e in errors):
            raise OperationFailure(str(exc))

        existing = max(0, len(documents) - inserted)
        return inserted, existing


async def _write_clone_batch(batch, stats):
    target, target_name = await _destination_collection()
    stats["target"] = target_name

    try:
        return await _bulk_clone_batch(target, batch)

    except OperationFailure as exc:
        if not MULTIPLE_DB or target_name != "Primary" or not _quota_error(exc):
            raise

        LOGGER.warning(
            "Primary quota reached during clone; switching batch to Media2"
        )

        stats["target"] = "Secondary"
        return await _bulk_clone_batch(Media2.collection, batch)


def _clone_control_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "▶️ Resume" if _clone_paused else "⏸ Pause",
                callback_data="clone:resume" if _clone_paused else "clone:pause",
            ),
            InlineKeyboardButton("⛔ Stop", callback_data="clone:cancel"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="clone:menu")],
    ])


async def _update_progress(message, source_name, total, stats, started):
    elapsed = time.time() - started
    percent = (stats["read"] / total * 100) if total else 0
    rate = stats["saved"] / elapsed if elapsed else 0
    pause_text = "⏸ PAUSED" if _clone_paused else "▶️ RUNNING"

    await message.edit_text(
        f"🚀 <b>Cloning {pause_text}</b>\n\n"
        f"🗄 Source: <code>{source_name}</code>\n"
        f"📁 Collection: <code>{stats['collection']}</code>\n"
        f"📊 Progress: <code>{percent:.1f}%</code>\n"
        f"📥 Read: <code>{stats['read']:,}/{total:,}</code>\n"
        f"💾 New: <code>{stats['saved']:,}</code>\n"
        f"🔁 Existing: <code>{stats['existing']:,}</code>\n"
        f"⚠️ Invalid: <code>{stats['invalid']:,}</code>\n"
        f"❌ Errors: <code>{stats['errors']:,}</code>\n"
        f"🎯 Target: <code>{stats['target']}</code>\n"
        f"⚡ Speed: <code>{rate:,.1f} new/sec</code>\n"
        f"⏱ Elapsed: <code>{_duration(elapsed)}</code>",
        reply_markup=_clone_control_keyboard(),
    )


async def _clone_source(source, message):
    global _clone_cancel, _clone_paused

    _clone_cancel = False
    _clone_paused = False
    client = None
    started = time.time()

    stats = {
        "read": 0, "saved": 0, "existing": 0, "invalid": 0,
        "errors": 0, "batches": 0, "target": "Primary",
        "collection": source["collection"],
    }

    try:
        client, source_db = await _source_client(source)
        source_collection = source_db[source["collection"]]
        total = await source_collection.estimated_document_count()
        source_name = _source_label(source)

        await message.edit_text(
            f"🚀 <b>Clone Started</b>\n\n"
            f"🗄 Source: <code>{source_name}</code>\n"
            f"🗃 Database: <code>{source['database']}</code>\n"
            f"📁 Collection: <code>{source['collection']}</code>\n"
            f"📦 Source documents: <code>{total:,}</code>\n\n"
            f"⏳ Reading MongoDB directly...",
            reply_markup=_clone_control_keyboard(),
        )

        cursor = source_collection.find({}, no_cursor_timeout=True).batch_size(BATCH_SIZE)
        batch = []
        last_update = time.time()

        try:
            async for raw in cursor:
                if _clone_cancel:
                    break

                while _clone_paused and not _clone_cancel:
                    await asyncio.sleep(1)

                if _clone_cancel:
                    break

                stats["read"] += 1
                cleaned, error = _clean_document(raw)

                if error:
                    stats["invalid"] += 1
                    continue

                batch.append(cleaned)

                if len(batch) >= BATCH_SIZE:
                    try:
                        inserted, existing = await _write_clone_batch(batch, stats)
                        stats["saved"] += inserted
                        stats["existing"] += existing
                        stats["batches"] += 1
                    except Exception:
                        stats["errors"] += len(batch)
                        LOGGER.exception("Clone batch write failed")

                    batch.clear()

                    if time.time() - last_update >= PROGRESS_EVERY:
                        await _update_progress(
                            message, source_name, total, stats, started
                        )
                        last_update = time.time()

            if batch and not _clone_cancel:
                try:
                    inserted, existing = await _write_clone_batch(batch, stats)
                    stats["saved"] += inserted
                    stats["existing"] += existing
                    stats["batches"] += 1
                except Exception:
                    stats["errors"] += len(batch)
                    LOGGER.exception("Final clone batch write failed")
        finally:
            await cursor.close()

        elapsed = time.time() - started
        title = "⛔ <b>Clone Stopped</b>" if _clone_cancel else "✅ <b>Clone Completed</b>"
        rate = stats["saved"] / elapsed if elapsed else 0

        await message.edit_text(
            f"{title}\n\n"
            f"🗄 Source: <code>{source_name}</code>\n"
            f"🗃 Database: <code>{source['database']}</code>\n"
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
                [InlineKeyboardButton("🔙 Back", callback_data="clone:menu")],
            ]),
        )

    except Exception as exc:
        LOGGER.exception("Clone failed")
        try:
            await message.edit_text(
                f"❌ <b>Clone Failed</b>\n\n<code>{str(exc)[:2500]}</code>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Sources", callback_data="clone:sources")],
                    [InlineKeyboardButton("🔙 Back", callback_data="clone:menu")],
                ]),
            )
        except Exception:
            pass
    finally:
        if client:
            client.close()


def _duration(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


async def _menu_text():
    sources = await _list_sources()
    return (
        "⚡ <b>MongoDB Clone Manager</b>\n\n"
        f"🔗 Sources: <code>{len(sources)}</code>\n"
        f"🚀 Status: <code>{'CLONING' if _clone_lock.locked() else 'IDLE'}</code>\n"
        f"🎯 Target: <code>{COLLECTION_NAME}</code>"
    )


def _menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add Source", callback_data="clone:add"),
            InlineKeyboardButton("📋 Sources", callback_data="clone:sources"),
        ],
        [
            InlineKeyboardButton("📊 Target Stats", callback_data="clone:stats"),
            InlineKeyboardButton("⛔ Stop Clone", callback_data="clone:cancel"),
        ],
        [InlineKeyboardButton("✖ Close", callback_data="clone:close")],
    ])


@Client.on_message(filters.command("clonemenu") & filters.user(ADMINS))
async def clone_menu(bot, message):
    await message.reply_text(await _menu_text(), reply_markup=_menu_keyboard())


@Client.on_message(filters.private & filters.incoming & filters.text & filters.user(ADMINS))
async def clone_text_receiver(bot, message):
    user_id = message.from_user.id
    state = _pending_add.get(user_id)

    if not state or message.text.startswith("/"):
        return

    text = message.text.strip()

    if state["step"] == "url":
        if not (text.startswith("mongodb://") or text.startswith("mongodb+srv://")):
            return await message.reply_text(
                "❌ Invalid MongoDB URL.\n\n"
                "It must start with <code>mongodb://</code> or <code>mongodb+srv://</code>"
            )

        status = await message.reply_text("🔌 <b>Checking MongoDB URL...</b>")
        client = None

        try:
            client = AsyncIOMotorClient(
                text, serverSelectionTimeoutMS=10000, connectTimeoutMS=10000
            )
            await client.admin.command("ping")

            state["url"] = text
            state["step"] = "database"

            await status.edit_text(
                "🔗 <b>MongoDB URL Added ✅</b>\n\n"
                f"🔐 URL: <code>{_mask_mongo_url(text)}</code>\n\n"
                "📂 <b>Now send the DATABASE NAME.</b>\n\n"
                "Example: <code>sandy</code>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="clone:add_back")],
                    [InlineKeyboardButton("✖ Cancel", callback_data="clone:canceladd")],
                ]),
            )
        except Exception as exc:
            await status.edit_text(
                f"❌ <b>MongoDB connection failed</b>\n\n<code>{str(exc)[:2000]}</code>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="clone:add")]
                ]),
            )
        finally:
            if client:
                client.close()
        return

    if state["step"] == "database":
        if not text or text.startswith("$"):
            return await message.reply_text("❌ Invalid database name.")

        state["database"] = text
        state["step"] = "collection"

        await message.reply_text(
            "📂 <b>Database Added Successfully ✅</b>\n\n"
            f"🗃 Database: <code>{text}</code>\n\n"
            "📁 <b>Now send the COLLECTION NAME.</b>\n\n"
            "Example: <code>sandy</code>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="clone:add_back")],
                [InlineKeyboardButton("✖ Cancel", callback_data="clone:canceladd")],
            ]),
        )
        return

    if state["step"] == "collection":
        if not text or text.startswith("system."):
            return await message.reply_text("❌ Invalid collection name.")

        client = None

        try:
            client = AsyncIOMotorClient(
                state["url"], serverSelectionTimeoutMS=10000, connectTimeoutMS=10000
            )
            await client.admin.command("ping")

            db = client[state["database"]]
            collections = await db.list_collection_names()

            if text not in collections:
                return await message.reply_text(
                    "❌ <b>Collection not found.</b>\n\n"
                    f"Database: <code>{state['database']}</code>\n"
                    f"Collection: <code>{text}</code>",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Back", callback_data="clone:add_back")],
                        [InlineKeyboardButton("✖ Cancel", callback_data="clone:canceladd")],
                    ]),
                )

            count = await db[text].estimated_document_count()

            doc = {
                "name": f"{state['database']}/{text}",
                "uri": state["url"],
                "database": state["database"],
                "collection": text,
                "created_at": datetime.utcnow(),
            }

            result = await _sources_col.insert_one(doc)
            _pending_add.pop(user_id, None)

            await message.reply_text(
                "✅ <b>SOURCE ADDED SUCCESSFULLY</b>\n\n"
                f"🔗 MongoDB URL: <code>{_mask_mongo_url(state['url'])}</code>\n"
                f"🗃 Database: <code>{state['database']}</code> ✅\n"
                f"📁 Collection: <code>{text}</code> ✅\n"
                f"📦 Documents: <code>{count:,}</code>\n\n"
                f"🆔 Source ID: <code>{str(result.inserted_id)[-6:]}</code>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚀 Clone Now", callback_data=f"clone:run:{result.inserted_id}")],
                    [InlineKeyboardButton("➕ Add Another", callback_data="clone:add")],
                    [InlineKeyboardButton("📋 Sources", callback_data="clone:sources")],
                    [InlineKeyboardButton("🔙 Back", callback_data="clone:menu")],
                ]),
            )
        except Exception as exc:
            await message.reply_text(
                f"❌ <b>Could not verify collection</b>\n\n<code>{str(exc)[:2000]}</code>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="clone:add_back")]
                ]),
            )
        finally:
            if client:
                client.close()


@Client.on_callback_query(filters.regex(r"^clone:"))
async def clone_callbacks(bot, query):
    global _clone_task, _clone_cancel, _clone_paused

    if not _is_admin(query.from_user.id):
        return await query.answer("Not allowed.", show_alert=True)

    data = query.data.split(":")
    action = data[1] if len(data) > 1 else ""

    if action == "close":
        _pending_add.pop(query.from_user.id, None)
        try:
            await query.message.delete()
        except Exception:
            pass
        return await query.answer()

    if action == "cancel":
        _clone_cancel = True
        _clone_paused = False
        if _clone_task and not _clone_task.done():
            return await query.answer(
                "Stop requested. Finishing current batch...", show_alert=True
            )
        return await query.answer("No clone is running.", show_alert=True)

    if action == "pause":
        if not _clone_lock.locked():
            return await query.answer("No clone is running.", show_alert=True)
        _clone_paused = True
        return await query.answer("Clone paused.", show_alert=True)

    if action == "resume":
        if not _clone_lock.locked():
            return await query.answer("No clone is running.", show_alert=True)
        _clone_paused = False
        return await query.answer("Clone resumed.", show_alert=True)

    if action == "canceladd":
        _pending_add.pop(query.from_user.id, None)
        return await query.message.edit_text(
            await _menu_text(), reply_markup=_menu_keyboard()
        )

    if action == "add_back":
        state = _pending_add.get(query.from_user.id)
        if not state:
            return await query.message.edit_text(
                await _menu_text(), reply_markup=_menu_keyboard()
            )

        if state.get("step") == "collection":
            state["step"] = "database"
            return await query.message.edit_text(
                "🔗 <b>MongoDB URL Added ✅</b>\n\n"
                f"📂 Database: <code>{state.get('database', '')}</code>\n\n"
                "Send the <b>DATABASE NAME</b> again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="clone:add")],
                    [InlineKeyboardButton("✖ Cancel", callback_data="clone:canceladd")],
                ]),
            )

        _pending_add[query.from_user.id] = {"step": "url"}
        return await query.message.edit_text(
            "➕ <b>Add MongoDB Source</b>\n\nSend the <b>MongoDB URL</b>.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="clone:menu")],
                [InlineKeyboardButton("✖ Cancel", callback_data="clone:canceladd")],
            ]),
        )

    if action == "add":
        if _clone_lock.locked():
            return await query.answer("A clone is currently running.", show_alert=True)

        _pending_add[query.from_user.id] = {"step": "url"}

        await query.message.edit_text(
            "➕ <b>Add MongoDB Source</b>\n\n"
            "Send the <b>source MongoDB URL</b>.\n\n"
            "The URL does <b>NOT</b> need to contain the database name.\n\n"
            "Example:\n"
            "<code>mongodb+srv://user:password@cluster.mongodb.net/?retryWrites=true&w=majority</code>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="clone:menu")],
                [InlineKeyboardButton("✖ Cancel", callback_data="clone:canceladd")],
            ]),
        )
        return await query.answer()

    if action == "menu":
        _pending_add.pop(query.from_user.id, None)
        return await query.message.edit_text(
            await _menu_text(), reply_markup=_menu_keyboard()
        )

    if action == "sources":
        sources = await _list_sources()
        rows = []

        for source in sources:
            sid = str(source["_id"])
            label = f"🗄 {_source_label(source)} • {source['collection']}"
            rows.append([
                InlineKeyboardButton(label[:60], callback_data=f"clone:source:{sid}")
            ])

        rows.append([InlineKeyboardButton("➕ Add Source", callback_data="clone:add")])
        rows.append([InlineKeyboardButton("🔙 Back", callback_data="clone:menu")])

        text = "📋 <b>Saved MongoDB Sources</b>\n\n"
        text += "No sources saved." if not sources else "Select a source:"

        return await query.message.edit_text(
            text, reply_markup=InlineKeyboardMarkup(rows)
        )

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
                [InlineKeyboardButton("🔙 Back", callback_data="clone:sources")],
            ]),
        )

    if action == "delete":
        source = await _get_source(data[2] if len(data) > 2 else "")
        if not source:
            return await query.answer("Source not found.", show_alert=True)

        await _sources_col.delete_one({"_id": source["_id"]})
        return await query.message.edit_text(
            await _menu_text(), reply_markup=_menu_keyboard()
        )

    if action == "stats":
        try:
            size1 = await check_db_size(Media.collection.database)
            text = (
                "📊 <b>Target Database</b>\n\n"
                f"Primary data size: <code>{size1 / 1024 / 1024:.1f} MB</code>\n"
                f"Limit: <code>{DB_CHANGE_LIMIT} MB</code>"
            )

            if MULTIPLE_DB:
                try:
                    stats2 = await Media2.collection.database.command("dbstats")
                    size2 = stats2.get("dataSize", 0)
                    text += f"\nSecondary data size: <code>{size2 / 1024 / 1024:.1f} MB</code>"
                except Exception:
                    pass

            text += (
                f"\n\nMedia: <code>{await Media.count_documents({}):,}</code>"
                f"\nMedia2: <code>{await Media2.count_documents({}):,}</code>"
            )
        except Exception as exc:
            text = f"❌ Stats error: <code>{str(exc)[:1000]}</code>"

        return await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="clone:stats")],
                [InlineKeyboardButton("🔙 Back", callback_data="clone:menu")],
            ]),
        )

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
            try:
                await _clone_source(source, query.message)
            finally:
                _clone_task = None
                _clone_paused = False

        return

    await query.answer()
