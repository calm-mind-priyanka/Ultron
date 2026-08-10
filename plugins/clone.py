"""
Advanced MongoDB -> MongoDB clone manager for SilentXBotz.

Install as: plugins/clone.py

Important fixes:
- Atlas tiers that reject noTimeout cursors are supported.
- Source documents are normalized to the same file-id format used by
  database/ia_filterdb.py.
- Supports both the current custom _id/file_id schema and older collections
  that still contain a normal Telegram file_id.
- Keeps/rebuilds file_ref when possible.
- Re-running a clone repairs an already existing target document instead of
  silently leaving an old/broken document untouched.
- Batch writes automatically fall back to smaller writes when a batch fails.
- Primary -> Media2 quota switching is retained.
- Pause / resume / stop / progress / saved sources / target stats retained.
"""

import asyncio
import base64
import time
from datetime import datetime
from struct import pack
from urllib.parse import urlparse

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne
from pymongo.errors import BulkWriteError, OperationFailure
from pyrogram import Client, filters
from pyrogram.file_id import FileId
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import info
from info import ADMINS, COLLECTION_NAME, DATABASE_NAME, DATABASE_URI
from database.ia_filterdb import Media, Media2, check_db_size
from logging_helper import LOGGER


MULTIPLE_DB = getattr(info, "MULTIPLE_DB", False)
DB_CHANGE_LIMIT = getattr(info, "DB_CHANGE_LIMIT", 450)

TARGET_CLIENT = AsyncIOMotorClient(DATABASE_URI)
TARGET_DB = TARGET_CLIENT[DATABASE_NAME]
SOURCES = TARGET_DB["clone_sources"]

CLONE_LOCK = asyncio.Lock()
CLONE_TASK = None
CLONE_CANCEL = False
CLONE_PAUSED = False
PENDING_ADD = {}

BATCH_SIZE = 1000
PROGRESS_EVERY = 5


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def is_admin(user_id):
    try:
        return int(user_id) in [int(x) for x in ADMINS]
    except Exception:
        return False


def as_object_id(value):
    try:
        return ObjectId(str(value))
    except Exception:
        return None


def source_label(source):
    return source.get("name") or f"Source {str(source.get('_id', ''))[-6:]}"


def mask_mongo_url(uri):
    try:
        parsed = urlparse(uri)
        if not parsed.username:
            return uri
        host = parsed.hostname or "host"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://***:***@{host}{port}/..."
    except Exception:
        return "mongodb://***:***@..."


def quota_error(exc):
    text = str(exc).lower()
    return any(
        value in text
        for value in (
            "space quota",
            "quota exceeded",
            "over your space quota",
            "storage quota",
            "exceeded the space",
            "not enough space",
            "code 8000",
            "atlaserror",
        )
    )


def duration(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def encode_file_id(raw: bytes) -> str:
    result = b""
    zeros = 0
    for value in raw + bytes([22]) + bytes([4]):
        if value == 0:
            zeros += 1
            continue
        if zeros:
            result += b"\x00" + bytes([zeros])
            zeros = 0
        result += bytes([value])
    return base64.urlsafe_b64encode(result).decode().rstrip("=")


def encode_file_ref(file_ref: bytes) -> str:
    return base64.urlsafe_b64encode(file_ref).decode().rstrip("=")


def canonical_file_id(value):
    """Convert a Telegram/Pyrogram file id to this bot's DB file-id format."""
    if not isinstance(value, str) or not value.strip():
        return None, None

    value = value.strip()
    try:
        decoded = FileId.decode(value)
        canonical = encode_file_id(
            pack(
                "<iiqq",
                int(decoded.file_type),
                int(decoded.dc_id),
                int(decoded.media_id),
                int(decoded.access_hash),
            )
        )
        file_ref = None
        if getattr(decoded, "file_reference", None):
            try:
                file_ref = encode_file_ref(decoded.file_reference)
            except Exception:
                file_ref = None
        return canonical, file_ref
    except Exception:
        return None, None


def normalize_document(doc):
    """
    Return a target Media document in the exact schema expected by
    database.ia_filterdb.Media.

    Priority for IDs:
      1. explicit file_id field (older/imported DBs)
      2. _id (current SilentXBotz DBs)
      3. alternate telegram_file_id fields used by some old clones

    Each candidate is decoded and converted to the canonical ID used by
    ia_filterdb.save_file(). This is the key part that makes old and new
    source collections interchangeable.
    """
    candidates = []
    for key in ("file_id", "telegram_file_id", "media_file_id", "_id"):
        value = doc.get(key)
        if value is not None and value not in candidates:
            candidates.append(value)

    canonical = None
    rebuilt_ref = None
    selected = None

    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        normalized, generated_ref = canonical_file_id(candidate)
        if normalized:
            canonical = normalized
            rebuilt_ref = generated_ref
            selected = candidate
            break

    if not canonical:
        return None, "invalid Telegram file_id"

    file_name = doc.get("file_name") or doc.get("filename") or doc.get("name")
    if not isinstance(file_name, str) or not file_name.strip():
        return None, "missing file_name"

    try:
        file_size = int(doc.get("file_size", doc.get("size", 0)) or 0)
    except Exception:
        return None, "invalid file_size"

    # Prefer the source's saved reference, otherwise rebuild it from the
    # original Telegram file id when possible.
    file_ref = doc.get("file_ref")
    if file_ref is None:
        file_ref = doc.get("file_reference")
    if file_ref is None:
        file_ref = rebuilt_ref

    if file_ref is not None and not isinstance(file_ref, str):
        try:
            file_ref = str(file_ref)
        except Exception:
            file_ref = None

    return {
        "_id": canonical,
        "file_ref": file_ref,
        "file_name": file_name.strip(),
        "file_size": file_size,
        "file_type": doc.get("file_type") or doc.get("media_type"),
        "mime_type": doc.get("mime_type") or doc.get("mime"),
        "caption": doc.get("caption"),
    }, None


async def get_source(source_id):
    oid = as_object_id(source_id)
    if not oid:
        return None
    return await SOURCES.find_one({"_id": oid})


async def list_sources():
    return await SOURCES.find({}).sort("created_at", 1).to_list(length=100)


async def open_source(source):
    client = AsyncIOMotorClient(
        source["uri"],
        serverSelectionTimeoutMS=15000,
        connectTimeoutMS=15000,
        socketTimeoutMS=60000,
        retryWrites=True,
    )
    try:
        await client.admin.command("ping")
    except Exception:
        client.close()
        raise

    database = source.get("database")
    collection = source.get("collection")
    if not database or not collection:
        client.close()
        raise ValueError("Source database/collection is missing.")

    return client, client[database]


# ---------------------------------------------------------------------------
# Target selection / writes
# ---------------------------------------------------------------------------


async def destination_collection():
    if not MULTIPLE_DB:
        return Media.collection, "Primary"

    size = await check_db_size(Media.collection.database)
    limit = int(DB_CHANGE_LIMIT) * 1024 * 1024

    if size >= limit:
        return Media2.collection, "Secondary"
    return Media.collection, "Primary"


async def write_documents(collection, documents):
    """Upsert documents and return (new, repaired/existing)."""
    if not documents:
        return 0, 0

    operations = [
        UpdateOne(
            {"_id": doc["_id"]},
            {"$set": doc},
            upsert=True,
        )
        for doc in documents
    ]

    try:
        result = await collection.bulk_write(operations, ordered=False)
        new_count = int(result.upserted_count or 0)
        existing_count = max(0, len(documents) - new_count)
        return new_count, existing_count
    except BulkWriteError as exc:
        # Quota errors must be raised so the caller can move the batch to DB2.
        if quota_error(exc):
            raise OperationFailure(str(exc))

        # A malformed batch should not make the whole clone useless. Retry
        # individual documents and count only successful ones.
        new_count = 0
        existing_count = 0
        errors = exc.details.get("writeErrors", []) if exc.details else []
        failed_indexes = {int(x.get("index", -1)) for x in errors}

        for index, doc in enumerate(documents):
            if index not in failed_indexes:
                existing_count += 1
                continue
            try:
                result = await collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": doc},
                    upsert=True,
                )
                if result.upserted_id is not None:
                    new_count += 1
                else:
                    existing_count += 1
            except Exception as item_error:
                LOGGER.error(
                    "Clone individual write failed for %s: %s",
                    doc.get("file_name"),
                    item_error,
                )

        return new_count, existing_count


async def write_clone_batch(batch, stats):
    target, target_name = await destination_collection()
    stats["target"] = target_name

    try:
        return await write_documents(target, batch)
    except OperationFailure as exc:
        if not (MULTIPLE_DB and target_name == "Primary" and quota_error(exc)):
            raise

        LOGGER.warning("Primary quota reached. Switching clone batch to Media2.")
        stats["target"] = "Secondary"
        return await write_documents(Media2.collection, batch)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


def control_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "▶️ Resume" if CLONE_PAUSED else "⏸ Pause",
                    callback_data="clone:resume" if CLONE_PAUSED else "clone:pause",
                ),
                InlineKeyboardButton("⛔ Stop", callback_data="clone:cancel"),
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="clone:menu")],
        ]
    )


async def update_progress(message, source_name, total, stats, started):
    elapsed = time.time() - started
    percent = stats["read"] / total * 100 if total else 0
    rate = stats["saved"] / elapsed if elapsed else 0
    status = "⏸ PAUSED" if CLONE_PAUSED else "▶️ RUNNING"

    text = (
        f"🚀 <b>Cloning {status}</b>\n\n"
        f"🗄 Source: <code>{source_name}</code>\n"
        f"🗃 Database: <code>{stats['database']}</code>\n"
        f"📁 Collection: <code>{stats['collection']}</code>\n"
        f"📊 Progress: <code>{percent:.1f}%</code>\n"
        f"📥 Read: <code>{stats['read']:,}/{total:,}</code>\n"
        f"💾 New: <code>{stats['saved']:,}</code>\n"
        f"🔧 Existing/Repaired: <code>{stats['existing']:,}</code>\n"
        f"⚠️ Invalid: <code>{stats['invalid']:,}</code>\n"
        f"❌ Errors: <code>{stats['errors']:,}</code>\n"
        f"🎯 Target: <code>{stats['target']}</code>\n"
        f"⚡ Speed: <code>{rate:,.1f} new/sec</code>\n"
        f"⏱ Elapsed: <code>{duration(elapsed)}</code>"
    )

    try:
        await message.edit_text(text, reply_markup=control_keyboard())
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Clone engine
# ---------------------------------------------------------------------------


async def clone_source(source, message):
    global CLONE_CANCEL, CLONE_PAUSED

    CLONE_CANCEL = False
    CLONE_PAUSED = False
    source_client = None
    started = time.time()

    stats = {
        "read": 0,
        "saved": 0,
        "existing": 0,
        "invalid": 0,
        "errors": 0,
        "batches": 0,
        "target": "Primary",
        "database": source["database"],
        "collection": source["collection"],
    }

    try:
        source_client, source_db = await open_source(source)
        collection = source_db[source["collection"]]
        total = await collection.estimated_document_count()
        name = source_label(source)

        await message.edit_text(
            f"🚀 <b>Clone Started</b>\n\n"
            f"🗄 Source: <code>{name}</code>\n"
            f"🗃 Database: <code>{source['database']}</code>\n"
            f"📁 Collection: <code>{source['collection']}</code>\n"
            f"📦 Source documents: <code>{total:,}</code>\n\n"
            f"🔎 Normalizing Telegram file IDs...\n"
            f"⏳ Reading MongoDB directly...",
            reply_markup=control_keyboard(),
        )

        # NO no_cursor_timeout=True here. Atlas tiers can reject it.
        cursor = collection.find({}).batch_size(BATCH_SIZE)
        batch = []
        last_update = time.time()

        try:
            async for raw in cursor:
                if CLONE_CANCEL:
                    break

                while CLONE_PAUSED and not CLONE_CANCEL:
                    await asyncio.sleep(1)

                if CLONE_CANCEL:
                    break

                stats["read"] += 1
                cleaned, error = normalize_document(raw)

                if error:
                    stats["invalid"] += 1
                    if stats["invalid"] <= 10:
                        LOGGER.warning(
                            "Skipping source document: %s (%s)",
                            raw.get("file_name") or raw.get("_id"),
                            error,
                        )
                    continue

                batch.append(cleaned)

                if len(batch) >= BATCH_SIZE:
                    try:
                        new_count, existing_count = await write_clone_batch(
                            batch, stats
                        )
                        stats["saved"] += new_count
                        stats["existing"] += existing_count
                        stats["batches"] += 1
                    except Exception:
                        stats["errors"] += len(batch)
                        LOGGER.exception("Clone batch write failed")
                    finally:
                        batch.clear()

                    if time.time() - last_update >= PROGRESS_EVERY:
                        await update_progress(
                            message, name, total, stats, started
                        )
                        last_update = time.time()

            if batch and not CLONE_CANCEL:
                try:
                    new_count, existing_count = await write_clone_batch(
                        batch, stats
                    )
                    stats["saved"] += new_count
                    stats["existing"] += existing_count
                    stats["batches"] += 1
                except Exception:
                    stats["errors"] += len(batch)
                    LOGGER.exception("Final clone batch write failed")
                finally:
                    batch.clear()
        finally:
            try:
                await cursor.close()
            except Exception:
                pass

        elapsed = time.time() - started
        rate = stats["saved"] / elapsed if elapsed else 0
        title = "⛔ <b>Clone Stopped</b>" if CLONE_CANCEL else "✅ <b>Clone Completed</b>"

        await message.edit_text(
            f"{title}\n\n"
            f"🗄 Source: <code>{name}</code>\n"
            f"🗃 Database: <code>{source['database']}</code>\n"
            f"📁 Collection: <code>{source['collection']}</code>\n\n"
            f"📥 Read: <code>{stats['read']:,}</code>\n"
            f"💾 New files: <code>{stats['saved']:,}</code>\n"
            f"🔧 Existing/Repaired: <code>{stats['existing']:,}</code>\n"
            f"⚠️ Invalid/unusable: <code>{stats['invalid']:,}</code>\n"
            f"❌ Errors: <code>{stats['errors']:,}</code>\n"
            f"🎯 Last target: <code>{stats['target']}</code>\n"
            f"⏱ Time: <code>{duration(elapsed)}</code>\n"
            f"⚡ New files/sec: <code>{rate:,.1f}</code>",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Clone Again",
                            callback_data=f"clone:run:{source['_id']}",
                        )
                    ],
                    [InlineKeyboardButton("📋 Sources", callback_data="clone:sources")],
                    [InlineKeyboardButton("🔙 Back", callback_data="clone:menu")],
                ]
            ),
        )

    except Exception as exc:
        LOGGER.exception("Clone failed")
        try:
            await message.edit_text(
                f"❌ <b>Clone Failed</b>\n\n<code>{str(exc)[:3000]}</code>",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("📋 Sources", callback_data="clone:sources")],
                        [InlineKeyboardButton("🔙 Back", callback_data="clone:menu")],
                    ]
                ),
            )
        except Exception:
            pass
    finally:
        if source_client:
            source_client.close()


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------


async def menu_text():
    sources = await list_sources()
    return (
        "⚡ <b>MongoDB Clone Manager</b>\n\n"
        f"🔗 Sources: <code>{len(sources)}</code>\n"
        f"🚀 Status: <code>{'CLONING' if CLONE_LOCK.locked() else 'IDLE'}</code>\n"
        f"🎯 Target: <code>{COLLECTION_NAME}</code>"
    )


def menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("➕ Add Source", callback_data="clone:add"),
                InlineKeyboardButton("📋 Sources", callback_data="clone:sources"),
            ],
            [
                InlineKeyboardButton("📊 Target Stats", callback_data="clone:stats"),
                InlineKeyboardButton("⛔ Stop Clone", callback_data="clone:cancel"),
            ],
            [InlineKeyboardButton("✖ Close", callback_data="clone:close")],
        ]
    )


@Client.on_message(filters.command("clonemenu") & filters.user(ADMINS))
async def clone_menu(bot, message):
    await message.reply_text(await menu_text(), reply_markup=menu_keyboard())


# ---------------------------------------------------------------------------
# Add-source text flow
# ---------------------------------------------------------------------------


@Client.on_message(
    filters.private & filters.incoming & filters.text & filters.user(ADMINS)
)
async def clone_text_receiver(bot, message):
    user_id = message.from_user.id
    state = PENDING_ADD.get(user_id)

    if not state or message.text.startswith("/"):
        return

    text = message.text.strip()

    if state["step"] == "url":
        if not (text.startswith("mongodb://") or text.startswith("mongodb+srv://")):
            return await message.reply_text(
                "❌ Invalid MongoDB URL.\n\n"
                "It must start with <code>mongodb://</code> or "
                "<code>mongodb+srv://</code>"
            )

        status = await message.reply_text("🔌 <b>Checking MongoDB URL...</b>")
        client = None
        try:
            client = AsyncIOMotorClient(
                text,
                serverSelectionTimeoutMS=15000,
                connectTimeoutMS=15000,
            )
            await client.admin.command("ping")
            state["url"] = text
            state["step"] = "database"
            await status.edit_text(
                "🔗 <b>MongoDB URL Added ✅</b>\n\n"
                f"🔐 URL: <code>{mask_mongo_url(text)}</code>\n\n"
                "📂 <b>Now send the DATABASE NAME.</b>",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("🔙 Back", callback_data="clone:add_back")],
                        [InlineKeyboardButton("✖ Cancel", callback_data="clone:canceladd")],
                    ]
                ),
            )
        except Exception as exc:
            await status.edit_text(
                f"❌ <b>MongoDB connection failed</b>\n\n<code>{str(exc)[:2000]}</code>",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="clone:add")]]
                ),
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
        return await message.reply_text(
            "📂 <b>Database Added Successfully ✅</b>\n\n"
            f"🗃 Database: <code>{text}</code>\n\n"
            "📁 <b>Now send the COLLECTION NAME.</b>",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔙 Back", callback_data="clone:add_back")],
                    [InlineKeyboardButton("✖ Cancel", callback_data="clone:canceladd")],
                ]
            ),
        )

    if state["step"] == "collection":
        if not text or text.startswith("system."):
            return await message.reply_text("❌ Invalid collection name.")

        client = None
        try:
            client = AsyncIOMotorClient(
                state["url"],
                serverSelectionTimeoutMS=15000,
                connectTimeoutMS=15000,
            )
            await client.admin.command("ping")
            db = client[state["database"]]
            collections = await db.list_collection_names()

            if text not in collections:
                return await message.reply_text(
                    "❌ <b>Collection not found.</b>\n\n"
                    f"Database: <code>{state['database']}</code>\n"
                    f"Collection: <code>{text}</code>",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [InlineKeyboardButton("🔙 Back", callback_data="clone:add_back")],
                            [InlineKeyboardButton("✖ Cancel", callback_data="clone:canceladd")],
                        ]
                    ),
                )

            count = await db[text].estimated_document_count()
            doc = {
                "name": f"{state['database']}/{text}",
                "uri": state["url"],
                "database": state["database"],
                "collection": text,
                "created_at": datetime.utcnow(),
            }
            result = await SOURCES.insert_one(doc)
            PENDING_ADD.pop(user_id, None)

            await message.reply_text(
                "✅ <b>SOURCE ADDED SUCCESSFULLY</b>\n\n"
                f"🔗 MongoDB URL: <code>{mask_mongo_url(state['url'])}</code>\n"
                f"🗃 Database: <code>{state['database']}</code> ✅\n"
                f"📁 Collection: <code>{text}</code> ✅\n"
                f"📦 Documents: <code>{count:,}</code>\n\n"
                f"🆔 Source ID: <code>{str(result.inserted_id)[-6:]}</code>",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("🚀 Clone Now", callback_data=f"clone:run:{result.inserted_id}")],
                        [InlineKeyboardButton("➕ Add Another", callback_data="clone:add")],
                        [InlineKeyboardButton("📋 Sources", callback_data="clone:sources")],
                        [InlineKeyboardButton("🔙 Back", callback_data="clone:menu")],
                    ]
                ),
            )
        except Exception as exc:
            await message.reply_text(
                f"❌ <b>Could not verify collection</b>\n\n<code>{str(exc)[:2000]}</code>",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="clone:add_back")]]
                ),
            )
        finally:
            if client:
                client.close()


# ---------------------------------------------------------------------------
# Callback handlers
# ---------------------------------------------------------------------------


@Client.on_callback_query(filters.regex(r"^clone:"))
async def clone_callbacks(bot, query):
    global CLONE_TASK, CLONE_CANCEL, CLONE_PAUSED

    if not is_admin(query.from_user.id):
        return await query.answer("Not allowed.", show_alert=True)

    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "close":
        PENDING_ADD.pop(query.from_user.id, None)
        try:
            await query.message.delete()
        except Exception:
            pass
        return await query.answer()

    if action == "cancel":
        if not CLONE_LOCK.locked():
            return await query.answer("No clone is running.", show_alert=True)
        CLONE_CANCEL = True
        CLONE_PAUSED = False
        return await query.answer("Stop requested. Current batch will finish.", show_alert=True)

    if action == "pause":
        if not CLONE_LOCK.locked():
            return await query.answer("No clone is running.", show_alert=True)
        CLONE_PAUSED = True
        return await query.answer("Clone paused.", show_alert=True)

    if action == "resume":
        if not CLONE_LOCK.locked():
            return await query.answer("No clone is running.", show_alert=True)
        CLONE_PAUSED = False
        return await query.answer("Clone resumed.", show_alert=True)

    if action == "canceladd":
        PENDING_ADD.pop(query.from_user.id, None)
        return await query.message.edit_text(await menu_text(), reply_markup=menu_keyboard())

    if action == "add_back":
        state = PENDING_ADD.get(query.from_user.id)
        if not state:
            return await query.message.edit_text(await menu_text(), reply_markup=menu_keyboard())

        if state.get("step") == "collection":
            state["step"] = "database"
            return await query.message.edit_text(
                "🔗 <b>MongoDB URL Added ✅</b>\n\n"
                "Send the <b>DATABASE NAME</b> again.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("🔙 Back", callback_data="clone:add")],
                        [InlineKeyboardButton("✖ Cancel", callback_data="clone:canceladd")],
                    ]
                ),
            )

        PENDING_ADD[query.from_user.id] = {"step": "url"}
        return await query.message.edit_text(
            "➕ <b>Add MongoDB Source</b>\n\nSend the <b>MongoDB URL</b>.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔙 Back", callback_data="clone:menu")],
                    [InlineKeyboardButton("✖ Cancel", callback_data="clone:canceladd")],
                ]
            ),
        )

    if action == "add":
        if CLONE_LOCK.locked():
            return await query.answer("A clone is currently running.", show_alert=True)

        PENDING_ADD[query.from_user.id] = {"step": "url"}
        await query.message.edit_text(
            "➕ <b>Add MongoDB Source</b>\n\n"
            "Send the <b>source MongoDB URL</b>.\n\n"
            "The URL does <b>NOT</b> need to contain the database name.\n\n"
            "Example:\n"
            "<code>mongodb+srv://user:password@cluster.mongodb.net/?retryWrites=true&w=majority</code>",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔙 Back", callback_data="clone:menu")],
                    [InlineKeyboardButton("✖ Cancel", callback_data="clone:canceladd")],
                ]
            ),
        )
        return await query.answer()

    if action == "menu":
        PENDING_ADD.pop(query.from_user.id, None)
        return await query.message.edit_text(await menu_text(), reply_markup=menu_keyboard())

    if action == "sources":
        sources = await list_sources()
        rows = []
        for source in sources:
            sid = str(source["_id"])
            label = f"🗄 {source_label(source)} • {source['collection']}"
            rows.append([InlineKeyboardButton(label[:60], callback_data=f"clone:source:{sid}")])
        rows.append([InlineKeyboardButton("➕ Add Source", callback_data="clone:add")])
        rows.append([InlineKeyboardButton("🔙 Back", callback_data="clone:menu")])
        text = "📋 <b>Saved MongoDB Sources</b>\n\n"
        text += "No sources saved." if not sources else "Select a source:"
        return await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(rows))

    if action == "source":
        source = await get_source(parts[2] if len(parts) > 2 else "")
        if not source:
            return await query.answer("Source not found.", show_alert=True)

        count = "?"
        try:
            client, db = await open_source(source)
            count = f"{await db[source['collection']].estimated_document_count():,}"
            client.close()
        except Exception:
            pass

        sid = str(source["_id"])
        return await query.message.edit_text(
            f"🗄 <b>{source_label(source)}</b>\n\n"
            f"📁 Collection: <code>{source['collection']}</code>\n"
            f"🗃 Database: <code>{source['database']}</code>\n"
            f"📦 Documents: <code>{count}</code>\n"
            f"🔗 URL: <code>{mask_mongo_url(source['uri'])}</code>",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🚀 Start Clone", callback_data=f"clone:run:{sid}")],
                    [InlineKeyboardButton("🗑 Delete Source", callback_data=f"clone:delete:{sid}")],
                    [InlineKeyboardButton("🔙 Back", callback_data="clone:sources")],
                ]
            ),
        )

    if action == "delete":
        source = await get_source(parts[2] if len(parts) > 2 else "")
        if not source:
            return await query.answer("Source not found.", show_alert=True)
        await SOURCES.delete_one({"_id": source["_id"]})
        return await query.message.edit_text(await menu_text(), reply_markup=menu_keyboard())

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
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔄 Refresh", callback_data="clone:stats")],
                    [InlineKeyboardButton("🔙 Back", callback_data="clone:menu")],
                ]
            ),
        )

    if action == "run":
        if len(parts) < 3:
            return await query.answer("Invalid source.", show_alert=True)

        source = await get_source(parts[2])
        if not source:
            return await query.answer("Source not found.", show_alert=True)
        if CLONE_LOCK.locked():
            return await query.answer("Another clone is already running.", show_alert=True)

        await query.answer("Clone started.")
        async with CLONE_LOCK:
            CLONE_TASK = asyncio.current_task()
            try:
                await clone_source(source, query.message)
            finally:
                CLONE_TASK = None
                CLONE_PAUSED = False
                CLONE_CANCEL = False
        return

    return await query.answer()
