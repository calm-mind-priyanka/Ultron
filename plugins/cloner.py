import time
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import InsertOne

try:
    from ia_filterdb import Media, Media2, MULTIPLE_DB, clean_filename, unpack_new_file_id
except ImportError:
    try:
        from database.ia_filterdb import Media, Media2, MULTIPLE_DB, clean_filename, unpack_new_file_id
    except ImportError:
        Media, Media2, MULTIPLE_DB = None, None, False
        clean_filename = lambda x: x
        unpack_new_file_id = None

ADMINS = [6046055058]  # Your Admin ID

TEMP_CONFIG = {}

CLONE_STATUS = {
    "is_running": False,
    "is_paused": False,
    "total_files": 0,
    "copied_files": 0,
    "start_time": 0
}

def is_admin(_, __, message: Message):
    user = message.from_user
    if not user:
        return False
    return user.id in ADMINS or str(user.id) in [str(x) for x in ADMINS]

admin_filter = filters.create(is_admin)

@Client.on_message(filters.command("clonemenu") & admin_filter)
async def clone_mode_menu(client: Client, message: Message):
    await show_main_menu(message)


async def show_main_menu(message: Message, edit: bool = False):
    chat_id = message.chat.id
    config = TEMP_CONFIG.get(chat_id, {})
    
    src_url = config.get("source_url", "Not Set ❌")
    src_col = config.get("source_col", "Not Set ❌")

    display_url = (src_url[:25] + "...") if len(src_url) > 25 else src_url

    text = (
        f"⚡ **Ultra-Fast Bulk Movie Cloner**\n\n"
        f"🔗 **Source URL:** `{display_url}`\n"
        f"📑 **Collection Name:** `{src_col}`\n\n"
        f"Target Databases: **Connected (Auto-Detect Active)**\n"
        f"Click below to configure or view stats:"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔗 Set Source URL", callback_data="btn_set_url")],
        [InlineKeyboardButton(f"📑 Set Collection Name", callback_data="btn_set_col")],
        [InlineKeyboardButton("📊 Show Source Stats", callback_data="show_source_stats")],
        [InlineKeyboardButton("🚀 Start Ultra-Fast Copy", callback_data="start_copy")],
        [InlineKeyboardButton("🔄 Reset Config", callback_data="reset_config"),
         InlineKeyboardButton("🔙 Close", callback_data="home_menu")]
    ])

    if edit:
        try:
            await message.edit_text(text, reply_markup=keyboard)
        except Exception:
            pass
    else:
        await message.reply_text(text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex("^(btn_set_url|btn_set_col|show_source_stats|start_copy|pause_copy|resume_copy|stop_copy|reset_config|home_menu|back_to_main)$"))
async def handle_button_actions(client: Client, query: CallbackQuery):
    if query.from_user.id not in ADMINS and str(query.from_user.id) not in [str(x) for x in ADMINS]:
        return await query.answer("⚠️ You are not authorized to use this!", show_alert=True)

    chat_id = query.from_user.id
    data = query.data
    TEMP_CONFIG[chat_id] = TEMP_CONFIG.get(chat_id, {})
    config = TEMP_CONFIG[chat_id]

    if data == "btn_set_url":
        config["waiting_for"] = "source_url"
        await query.message.edit_text(
            "🔗 **Enter Source MongoDB URL**\n\n"
            "Please send your remote source MongoDB connection string in the chat now:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel / Back", callback_data="back_to_main")]])
        )
        await query.answer()

    elif data == "btn_set_col":
        config["waiting_for"] = "source_col"
        await query.message.edit_text(
            "📑 **Enter Source Collection Name**\n\n"
            "Please send the collection name where movie files are stored (e.g., `sdyimdx`):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel / Back", callback_data="back_to_main")]])
        )
        await query.answer()

    elif data == "show_source_stats":
        if not config.get("source_url") or not config.get("source_col"):
            return await query.answer("⚠️ Please set both Source URL and Collection Name first!", show_alert=True)
        
        await query.answer("📊 Scanning databases for collection...")
        try:
            temp_client = AsyncIOMotorClient(config["source_url"])
            target_col_name = config.get("source_col")
            
            dbs = await temp_client.list_database_names()
            found_db = None
            file_count = 0

            for db_n in dbs:
                if db_n in ["admin", "local", "config"]:
                    continue
                colls = await temp_client[db_n].list_collection_names()
                if target_col_name in colls:
                    found_db = db_n
                    file_count = await temp_client[db_n][target_col_name].count_documents({})
                    break

            if not found_db:
                found_db = "Cluster Default"
                file_count = 0

            stats_text = (
                f"📊 **Source Database Analytics**\n\n"
                f"🗂️ Matched DB Name: `{found_db}`\n"
                f"📁 Movie Files Found: `{file_count}`\n"
                f"✨ *(Status: Ready for ultra-fast copying)*"
            )
            
            await query.message.edit_text(
                stats_text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_main")]])
            )
        except Exception as e:
            await query.answer(f"Failed: {str(e)[:40]}", show_alert=True)

    elif data == "back_to_main":
        config["waiting_for"] = None
        await show_main_menu(query.message, edit=True)
        await query.answer()

    elif data == "reset_config":
        TEMP_CONFIG[chat_id] = {}
        await query.answer("Configuration reset!", show_alert=True)
        await show_main_menu(query.message, edit=True)

    elif data == "start_copy":
        if not config.get("source_url") or not config.get("source_col"):
            return await query.answer("⚠️ Please configure Source URL and Collection Name first!", show_alert=True)
        
        if CLONE_STATUS["is_running"]:
            return await query.answer("⚠️ A copy process is already running!", show_alert=True)

        await query.answer("🚀 Initializing Smart Bulk Migration...")
        asyncio.create_task(run_bulk_cloner(client, query.message, config))

    elif data == "pause_copy":
        CLONE_STATUS["is_paused"] = True
        await query.answer("⏸️ Paused process.", show_alert=True)
        await update_status_ui(query.message, "PAUSED")

    elif data == "resume_copy":
        CLONE_STATUS["is_paused"] = False
        await query.answer("▶️ Resumed process.", show_alert=True)

    elif data == "stop_copy":
        CLONE_STATUS["is_running"] = False
        await query.answer("🛑 Stopping process...", show_alert=True)

    elif data == "home_menu":
        try:
            await query.message.delete()
        except Exception:
            pass


@Client.on_message(filters.text & admin_filter)
async def capture_button_inputs(client: Client, message: Message):
    chat_id = message.from_user.id
    config = TEMP_CONFIG.get(chat_id, {})
    waiting_for = config.get("waiting_for")

    if not waiting_for:
        return

    text_val = message.text.strip()
    
    if waiting_for == "source_url":
        config["source_url"] = text_val
        config["waiting_for"] = None
        await message.reply_text("✅ Source URL Saved!")
        await show_main_menu(message, edit=False)

    elif waiting_for == "source_col":
        config["source_col"] = text_val
        config["waiting_for"] = None
        await message.reply_text("✅ Collection Name Saved!")
        await show_main_menu(message, edit=False)


async def run_bulk_cloner(client: Client, message: Message, config: dict):
    try:
        source_client = AsyncIOMotorClient(config["source_url"])
        target_col_name = config["source_col"]
        
        dbs = await source_client.list_database_names()
        source_col = None
        
        for db_n in dbs:
            if db_n in ["admin", "local", "config"]:
                continue
            colls = await source_client[db_n].list_collection_names()
            if target_col_name in colls:
                source_col = source_client[db_n][target_col_name]
                break
                
        if source_col is None:
            raise Exception(f"Collection '{target_col_name}' could not be found anywhere in the cluster!")

        CLONE_STATUS["total_files"] = await source_col.count_documents({})
        cursor = source_col.find({})
        
        CLONE_STATUS["is_running"] = True
        CLONE_STATUS["is_paused"] = False
        CLONE_STATUS["start_time"] = time.time()
        CLONE_STATUS["copied_files"] = 0

        if Media is None:
            raise Exception("Media database model could not be imported from your project!")

        target_collection = Media.collection
        batch_size = 5000  # Updated batch size to 5000
        bulk_operations = []

        async for movie in cursor:
            while CLONE_STATUS["is_paused"]:
                await asyncio.sleep(2)
                if not CLONE_STATUS["is_running"]:
                    break
            
            if not CLONE_STATUS["is_running"]:
                break

            raw_file_id = movie.get("file_id") or movie.get("_id")
            if raw_file_id:
                file_ref = movie.get("file_ref")
                
                # Automatically decode and harmonize file references if unpack function is available
                if unpack_new_file_id:
                    try:
                        parsed_id, parsed_ref = unpack_new_file_id(raw_file_id)
                        if parsed_id:
                            raw_file_id = parsed_id
                        if parsed_ref and not file_ref:
                            file_ref = parsed_ref
                    except Exception:
                        pass

                raw_filename = movie.get("file_name", "unknown")
                cleaned_name = clean_filename(raw_filename) if clean_filename else raw_filename

                doc = {
                    "_id": raw_file_id,
                    "file_id": raw_file_id,
                    "file_ref": file_ref,
                    "file_name": cleaned_name,
                    "file_size": movie.get("file_size", 0),
                    "file_type": movie.get("file_type", "document"),
                    "mime_type": movie.get("mime_type", "video/mp4"),
                    "caption": movie.get("caption", "")
                }
                bulk_operations.append(InsertOne(doc))

            if len(bulk_operations) >= batch_size:
                try:
                    await target_collection.bulk_write(bulk_operations, ordered=False)
                except Exception:
                    pass
                
                CLONE_STATUS["copied_files"] += len(bulk_operations)
                bulk_operations = []
                try:
                    await update_status_ui(message, "RUNNING")
                except Exception:
                    pass

        if bulk_operations and CLONE_STATUS["is_running"]:
            try:
                await target_collection.bulk_write(bulk_operations, ordered=False)
            except Exception:
                pass
            CLONE_STATUS["copied_files"] += len(bulk_operations)

        CLONE_STATUS["is_running"] = False
        await message.edit_text("⚡ **Ultra-Fast Bulk Cloning & File Harmonization Completed Successfully!**")

    except Exception as e:
        CLONE_STATUS["is_running"] = False
        await message.edit_text(f"❌ **Cloning Failed:** `{str(e)}`")


async def update_status_ui(message: Message, state: str):
    elapsed = int(time.time() - CLONE_STATUS["start_time"])
    m, s = divmod(elapsed, 60)
    
    text = (
        f"⚡ **Clone Mode Status: {state}**\n\n"
        f"📂 Total Movies in Source: `{CLONE_STATUS['total_files']}`\n"
        f"🚀 Copied Files: `{CLONE_STATUS['copied_files']}`\n"
        f"⏱️ Time Elapsed: `{m}m {s}s`\n"
    )
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏸️ Pause", callback_data="pause_copy") if state == "RUNNING" else InlineKeyboardButton("▶️ Resume", callback_data="resume_copy"),
            InlineKeyboardButton("🛑 Stop", callback_data="stop_copy")
        ],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_main")]
    ])
    
    try:
        await message.edit_text(text, reply_markup=keyboard)
    except Exception:
        pass
