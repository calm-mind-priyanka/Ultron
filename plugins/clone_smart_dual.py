import asyncio
import time
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, BulkWriteError
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database.ia_filterdb import Media, Media2
from info import MULTIPLE_DB

ADMINS = [6046055058] 

multi_clone_state = {
    "is_running": False,
    "is_paused": False,
    "is_cancelled": False,
    "current_count": 0,
    "skipped_count": 0,
    "sources_list": [], 
    "start_time": 0,
    "total_estimated_docs": 0,
}

user_input_state = {}

def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes, secs = divmod(seconds, 60)
        return f"{minutes}m {secs}s"
    else:
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours}h {minutes}m {secs}s"

@Client.on_message(filters.command("clonemenu") & filters.user(ADMINS))
async def clone_menu_command(client, message):
    await show_main_menu(message, is_edit=False)

async def show_main_menu(message_or_callback, is_edit=True):
    total_sources = len(multi_clone_state["sources_list"])
    db_mode = "Dual DB (Media & Media2 Active 🟢)" if MULTIPLE_DB else "Single DB Mode (Media Only)"
    
    keyboard = [
        [InlineKeyboardButton("➕ Add New Source DB & Collection", callback_data="add_source_url")],
        [InlineKeyboardButton(f"📋 View Connected Sources ({total_sources})", callback_data="view_sources")],
        [InlineKeyboardButton("⚙️ Start Smart Clone Process", callback_data="start_multi_clone")],
        [InlineKeyboardButton("🗑️ Clear / Reset Everything", callback_data="clear_menu")]
    ]
    
    text = (
        "🎛️ **Smart Multi-Source & Dual-DB Clone Manager**\n\n"
        f"• Target Mode: **{db_mode}**\n"
        f"• Connected Sources Ready: **{total_sources}**\n"
        "• *Note:* Duplicates are automatically skipped, and if Primary DB fills up, writes auto-switch to Media2."
    )
    
    if is_edit:
        try:
            await message_or_callback.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            await message_or_callback.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await message_or_callback.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

@Client.on_callback_query(filters.user(ADMINS))
async def multi_clone_callback_handler(client, callback_query: CallbackQuery):
    global multi_clone_state, user_input_state
    data = callback_query.data
    user_id = callback_query.from_user.id

    if data == "add_source_url":
        user_input_state[user_id] = {"step": "awaiting_multi_url"}
        await callback_query.message.edit_text(
            "🔗 **Step 1/3: Add Source MongoDB URL**\n\n"
            "Please send your source MongoDB connection URI in chat:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]])
        )
        await callback_query.answer()

    elif data == "view_sources":
        if not multi_clone_state["sources_list"]:
            await callback_query.answer("⚠️ No source databases added yet!", show_alert=True)
            return
        
        await callback_query.answer("📊 Fetching live statistics...")
        sources_text = "📋 **Connected Source Details & Stats:**\n\n"
        
        for i, src in enumerate(multi_clone_state["sources_list"], 1):
            url = src["url"]
            db_name = src["database"]
            col_name = src["collection"]
            masked_url = url.split("@")[-1] if "@" in url else url
            file_count = 0
            
            try:
                def get_count():
                    tc = MongoClient(url, serverSelectionTimeoutMS=4000)
                    return tc[db_name][col_name].estimated_document_count()
                file_count = await asyncio.to_thread(get_count)
            except Exception as e:
                file_count = f"Error: {e}"
            
            sources_text += (
                f"{i}. `...{masked_url}`\n"
                f"   🗄️ Database: `{db_name}`\n"
                f"   📁 Collection: `{col_name}`\n"
                f"   📦 Total Documents: **{file_count}**\n\n"
            )

        keyboard = [
            [InlineKeyboardButton("🗑️ Clear All Sources", callback_data="clear_sources_list")],
            [InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]
        ]
        await callback_query.message.edit_text(sources_text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "clear_sources_list":
        multi_clone_state["sources_list"] = []
        await callback_query.answer("🧹 All source databases cleared!")
        await show_main_menu(callback_query.message, is_edit=True)

    elif data == "start_multi_clone":
        if multi_clone_state["is_running"]:
            await callback_query.answer("⚠️ Cloning process is already active!", show_alert=True)
            return
        
        if not multi_clone_state["sources_list"]:
            await callback_query.answer("⚠️ Please add at least one source database first!", show_alert=True)
            return

        await callback_query.message.edit_text("🔄 **Initializing Smart Dual-DB cloning...**")
        asyncio.create_task(run_smart_cloning_process(client, callback_query.message))
        await callback_query.answer()

    elif data == "pause_clone":
        if multi_clone_state["is_running"] and not multi_clone_state["is_paused"]:
            multi_clone_state["is_paused"] = True
            await callback_query.answer("⏸️ Clone Paused.")
            await update_live_multi_panel(callback_query.message)

    elif data == "resume_clone":
        if multi_clone_state["is_running"] and multi_clone_state["is_paused"]:
            multi_clone_state["is_paused"] = False
            await callback_query.answer("▶️ Clone Resumed.")
            await update_live_multi_panel(callback_query.message)

    elif data == "cancel_clone":
        if multi_clone_state["is_running"]:
            multi_clone_state["is_cancelled"] = True
            multi_clone_state["is_paused"] = False
            await callback_query.answer("🛑 Stopping process safely...")

    elif data == "clear_menu":
        multi_clone_state["sources_list"] = []
        multi_clone_state["is_running"] = False
        user_input_state.pop(user_id, None)
        try:
            await callback_query.message.delete()
        except Exception:
            pass

    elif data == "back_to_menu":
        if multi_clone_state["is_running"]:
            await callback_query.answer("⚠️ Cannot return while cloning is running!", show_alert=True)
            return
        await show_main_menu(callback_query.message, is_edit=True)

@Client.on_message(filters.text & filters.user(ADMINS))
async def capture_multi_url_input(client, message):
    global user_input_state, multi_clone_state
    user_id = message.from_user.id

    if user_id in user_input_state:
        state_data = user_input_state[user_id]
        step = state_data.get("step")

        if step == "awaiting_multi_url":
            url = message.text.strip()
            if not url.startswith("mongodb"):
                await message.reply_text("❌ Invalid MongoDB URI format! Please send a valid URI.")
                return

            user_input_state[user_id] = {
                "step": "awaiting_database_name",
                "url": url
            }
            await message.reply_text(
                "🗄️ **Step 2/3: Enter Database Name**\n\n"
                "Please type the name of the database you want to connect to (e.g., `telegram_bot`, `my_db`, `cluster0`):"
            )

        elif step == "awaiting_database_name":
            db_name = message.text.strip()
            url = state_data.get("url")

            user_input_state[user_id] = {
                "step": "awaiting_collection_name",
                "url": url,
                "database": db_name
            }
            await message.reply_text(
                "📁 **Step 3/3: Enter Collection Name**\n\n"
                "Please type the exact collection name you want to read files from (e.g., `sdyimdx`, `Media`, `files`):"
            )

        elif step == "awaiting_collection_name":
            col_name = message.text.strip()
            url = state_data.get("url")
            db_name = state_data.get("database")

            multi_clone_state["sources_list"].append({
                "url": url,
                "database": db_name,
                "collection": col_name
            })
            user_input_state.pop(user_id, None)

            total_count = len(multi_clone_state["sources_list"])
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Another Source", callback_data="add_source_url")],
                [InlineKeyboardButton("⚙️ Start Cloning All", callback_data="start_multi_clone")],
                [InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]
            ])
            await message.reply_text(
                f"✅ **Source Added Successfully!**\n\n"
                f"• Database: `{db_name}`\n"
                f"• Collection: `{col_name}`\n"
                f"• Total sources configured: **{total_count}**",
                reply_markup=keyboard
            )

async def update_live_multi_panel(message):
    try:
        elapsed = time.time() - multi_clone_state["start_time"] if multi_clone_state["start_time"] > 0 else 0
        copied = multi_clone_state["current_count"]
        skipped = multi_clone_state["skipped_count"]
        
        status_text = (
            f"🔄 **Smart Cloning Live Status:**\n\n"
            f"📦 Successfully Copied: `{copied:,}` files\n"
            f"⏭️ Skipped Duplicates: `{skipped:,}` files\n"
            f"⏱️ Time Elapsed: `{format_duration(elapsed)}`\n"
            f"⚡ State: `{'PAUSED ⏸️' if multi_clone_state['is_paused'] else 'RUNNING 🚀'}`"
        )
        
        buttons = []
        if multi_clone_state["is_paused"]:
            buttons.append(InlineKeyboardButton("▶️ Resume", callback_data="resume_clone"))
        else:
            buttons.append(InlineKeyboardButton("⏸️ Pause", callback_data="pause_clone"))
        
        buttons.append(InlineKeyboardButton("🛑 Cancel & Stop", callback_data="cancel_clone"))
        
        keyboard = [buttons, [InlineKeyboardButton("« Back to Main Menu", callback_data="back_to_menu")]]
        await message.edit_text(status_text, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        pass

async def insert_batch_with_fallback(batch):
    if not batch:
        return 0, 0

    inserted_count = 0
    skipped_count = 0

    def do_inserts():
        nonlocal inserted_count, skipped_count
        try:
            result = Media.collection.insert_many(batch, ordered=False)
            inserted_count = len(result.inserted_ids)
        except BulkWriteError as bwe:
            details = bwe.details
            inserted_count = details.get('nInserted', 0)
            skipped_count = len(batch) - inserted_count
        except DuplicateKeyError:
            skipped_count = len(batch)
        except Exception as primary_error:
            err_str = str(primary_error).lower()
            if any(w in err_str for w in ["quota", "full", "block", "storage", "exceeded"]):
                if MULTIPLE_DB and Media2:
                    try:
                        result = Media2.collection.insert_many(batch, ordered=False)
                        inserted_count = len(result.inserted_ids)
                    except BulkWriteError as bwe2:
                        details2 = bwe2.details
                        inserted_count = details2.get('nInserted', 0)
                        skipped_count = len(batch) - inserted_count
                    except Exception:
                        skipped_count = len(batch)
                else:
                    for doc in batch:
                        try:
                            Media.collection.insert_one(doc)
                            inserted_count += 1
                        except Exception:
                            skipped_count += 1
            else:
                for doc in batch:
                    try:
                        Media.collection.insert_one(doc)
                        inserted_count += 1
                    except Exception:
                        skipped_count += 1

    await asyncio.to_thread(do_inserts)
    return inserted_count, skipped_count

async def run_smart_cloning_process(client, message):
    global multi_clone_state
    multi_clone_state["is_running"] = True
    multi_clone_state["is_paused"] = False
    multi_clone_state["is_cancelled"] = False
    multi_clone_state["current_count"] = 0
    multi_clone_state["skipped_count"] = 0
    multi_clone_state["start_time"] = time.time()
    multi_clone_state["total_estimated_docs"] = 0

    grand_total_copied = 0
    grand_total_skipped = 0

    try:
        for src in multi_clone_state["sources_list"]:
            try:
                def get_est():
                    tc = MongoClient(src["url"], serverSelectionTimeoutMS=4000)
                    return tc[src["database"]][src["collection"]].estimated_document_count()
                multi_clone_state["total_estimated_docs"] += await asyncio.to_thread(get_est)
            except Exception:
                pass

        await update_live_multi_panel(message)

        for src in multi_clone_state["sources_list"]:
            if multi_clone_state["is_cancelled"]:
                break

            source_uri = src["url"]
            db_name = src["database"].strip()
            collection_name = src["collection"].strip()

            try:
                def fetch_cursor():
                    sc = MongoClient(source_uri, serverSelectionTimeoutMS=10000)
                    return sc[db_name][collection_name].find({}).batch_size(2000)
                cursor = await asyncio.to_thread(fetch_cursor)
            except Exception as e:
                print(f"Connection error to source: {e}")
                continue

            batch = []
            try:
                # Use to_thread or async fetching loop with yields
                while True:
                    if multi_clone_state["is_cancelled"]:
                        break

                    while multi_clone_state["is_paused"]:
                        if multi_clone_state["is_cancelled"]:
                            break
                        await asyncio.sleep(2)

                    if multi_clone_state["is_cancelled"]:
                        break

                    # Fetch docs in a non-blocking way
                    def get_next_batch():
                        chunk = []
                        try:
                            for _ in range(500):
                                doc = cursor.next()
                                chunk.append(doc)
                        except StopIteration:
                            pass
                        return chunk

                    docs_chunk = await asyncio.to_thread(get_next_batch)
                    if not docs_chunk:
                        break

                    for doc in docs_chunk:
                        clean_doc = dict(doc)
                        clean_doc.pop("_id", None)
                        batch.append(clean_doc)

                    if len(batch) >= 2000:
                        ins, skp = await insert_batch_with_fallback(batch)
                        grand_total_copied += ins
                        grand_total_skipped += skp
                        
                        multi_clone_state["current_count"] = grand_total_copied
                        multi_clone_state["skipped_count"] = grand_total_skipped
                        batch = []
                        await update_live_multi_panel(message)
                        await asyncio.sleep(0.1) # Yield control back to telegram loop
            finally:
                try:
                    cursor.close()
                except Exception:
                    pass

            if batch and not multi_clone_state["is_cancelled"]:
                ins, skp = await insert_batch_with_fallback(batch)
                grand_total_copied += ins
                grand_total_skipped += skp
                multi_clone_state["current_count"] = grand_total_copied
                multi_clone_state["skipped_count"] = grand_total_skipped

        total_time_taken = time.time() - multi_clone_state["start_time"]

        if multi_clone_state["is_cancelled"]:
            await message.edit_text(
                f"❌ **Cloning Cancelled Safely!**\n\n"
                f"• Successfully Copied: `{grand_total_copied:,}` files\n"
                f"• Skipped Duplicates: `{grand_total_skipped:,}` files\n"
                f"⏱️ Time Taken: `{format_duration(total_time_taken)}`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Main Menu", callback_data="back_to_menu")]])
            )
        else:
            await message.edit_text(
                f"✅ **All Sources Cloned Successfully!**\n\n"
                f"• Total Files Saved: **{grand_total_copied:,}**\n"
                f"• Duplicate Files Skipped: **{grand_total_skipped:,}**\n"
                f"⏱️ Total Time Taken: **{format_duration(total_time_taken)}**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Main Menu", callback_data="back_to_menu")]])
            )

    except Exception as e:
        await message.edit_text(
            f"❌ **Clone Failed:**\n<code>{str(e)}</code>", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Main Menu", callback_data="back_to_menu")]])
        )
    finally:
        multi_clone_state["is_running"] = False
        multi_clone_state["is_paused"] = False
        multi_clone_state["is_cancelled"] = False
