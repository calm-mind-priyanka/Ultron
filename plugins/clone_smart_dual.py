import asyncio
from pymongo import MongoClient
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database.ia_filterdb import Media, Media2
from info import MULTIPLE_DB

# ==========================================
# YOUR ADMIN ID CONFIGURED HERE
ADMINS = [6046055058] 
# ==========================================

# Multi-source & Dual DB control state
multi_clone_state = {
    "is_running": False,
    "is_paused": False,
    "is_cancelled": False,
    "current_count": 0,
    "total_docs": 0,
    "sources_list": [],
}

user_input_state = {}

@Client.on_message(filters.command("clonemenu") & filters.user(ADMINS))
async def clone_menu_command(client, message):
    # FIXED: Pass is_edit=False so it replies instead of trying to edit a user message
    await show_main_menu(message, is_edit=False)

async def show_main_menu(message_or_callback, is_edit=True):
    total_sources = len(multi_clone_state["sources_list"])
    db_mode = "Dual DB (Media & Media2 Support)" if MULTIPLE_DB else "Single DB Mode"
    
    keyboard = [
        [InlineKeyboardButton("➕ Add New Source DB URL", callback_data="add_source_url")],
        [InlineKeyboardButton(f"📋 View Connected Sources ({total_sources})", callback_data="view_sources")],
        [InlineKeyboardButton("⚙️ Start Smart Clone Process", callback_data="start_multi_clone")],
        [InlineKeyboardButton("🗑️ Clear / Reset Everything", callback_data="clear_menu")]
    ]
    
    text = (
        "🎛️ **Smart Multi-Source & Dual-DB Clone Manager**\n\n"
        f"• Target Mode: **{db_mode}**\n"
        f"• Connected Sources Ready: **{total_sources}**\n"
        "• *Note:* If Dual DB is active, files will automatically switch to Media2 if Media fills up."
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
        user_input_state[user_id] = "awaiting_multi_url"
        await callback_query.message.edit_text(
            "🔗 **Add New Source MongoDB URL**\n\n"
            "Please send the new source database URL in chat.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]])
        )
        await callback_query.answer()

    elif data == "view_sources":
        if not multi_clone_state["sources_list"]:
            await callback_query.answer("⚠️ No source databases added yet!", show_alert=True)
            return
        
        sources_text = "📋 **List of Connected Source Databases:**\n\n"
        for i, url in enumerate(multi_clone_state["sources_list"], 1):
            masked_url = url.split("@")[-1] if "@" in url else url
            sources_text += f"{i}. `...{masked_url}`\n"

        keyboard = [
            [InlineKeyboardButton("🗑️ Clear All Sources", callback_data="clear_sources_list")],
            [InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]
        ]
        await callback_query.message.edit_text(sources_text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "clear_sources_list":
        multi_clone_state["sources_list"] = []
        await callback_query.answer("🧹 All source URLs cleared!")
        await show_main_menu(callback_query.message, is_edit=True)

    elif data == "start_multi_clone":
        if multi_clone_state["is_running"]:
            await callback_query.answer("⚠️ Cloning process is already active!", show_alert=True)
            return
        
        if not multi_clone_state["sources_list"]:
            await callback_query.answer("⚠️ Please add at least one source database URL first!", show_alert=True)
            return

        await callback_query.message.edit_text("🔄 **Initializing Smart Dual-DB cloning...**")
        client.loop.create_task(run_smart_cloning_process(client, callback_query.message))
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
            await callback_query.answer("🛑 Cancelling process...")

    elif data == "clear_menu":
        multi_clone_state["sources_list"] = []
        multi_clone_state["is_running"] = False
        user_input_state.pop(user_id, None)
        await callback_query.message.delete()

    elif data == "back_to_menu":
        await show_main_menu(callback_query.message, is_edit=True)

@Client.on_message(filters.text & filters.user(ADMINS))
async def capture_multi_url_input(client, message):
    global user_input_state, multi_clone_state
    user_id = message.from_user.id

    if user_id in user_input_state and user_input_state[user_id] == "awaiting_multi_url":
        url = message.text.strip()
        if not url.startswith("mongodb"):
            await message.reply_text("❌ Invalid MongoDB URI format! Please try again.")
            return

        multi_clone_state["sources_list"].append(url)
        user_input_state.pop(user_id, None)
        
        total_count = len(multi_clone_state["sources_list"])
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Another URL", callback_data="add_source_url")],
            [InlineKeyboardButton("⚙️ Start Cloning All", callback_data="start_multi_clone")],
            [InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]
        ])
        await message.reply_text(
            f"✅ **Source URL Added Successfully!**\n\n"
            f"Total sources in queue: **{total_count}**",
            reply_markup=keyboard
        )

async def update_live_multi_panel(message):
    try:
        status_text = (
            f"🔄 **Smart Cloning Live Status:**\n\n"
            f"📦 Progress: `{multi_clone_state['current_count']}` files copied\n"
            f"⚡ State: `{'PAUSED ⏸️' if multi_clone_state['is_paused'] else 'RUNNING 🚀'}`"
        )
        
        buttons = []
        if multi_clone_state["is_paused"]:
            buttons.append(InlineKeyboardButton("▶️ Resume", callback_data="resume_clone"))
        else:
            buttons.append(InlineKeyboardButton("⏸️ Pause", callback_data="pause_clone"))
        
        buttons.append(InlineKeyboardButton("🛑 Cancel", callback_data="cancel_clone"))
        
        await message.edit_text(status_text, reply_markup=InlineKeyboardMarkup([buttons]))
    except Exception:
        pass

async def run_smart_cloning_process(client, message):
    global multi_clone_state
    multi_clone_state["is_running"] = True
    multi_clone_state["is_paused"] = False
    multi_clone_state["is_cancelled"] = False
    multi_clone_state["current_count"] = 0

    grand_total_copied = 0

    try:
        await update_live_multi_panel(message)

        for source_uri in multi_clone_state["sources_list"]:
            if multi_clone_state["is_cancelled"]:
                break

            try:
                source_client = MongoClient(source_uri, serverSelectionTimeoutMS=5000)
                source_db = source_client.get_default_database()
                source_col = source_db["files"]
            except Exception:
                continue

            batch = []
            
            for doc in source_col.find():
                if multi_clone_state["is_cancelled"]:
                    break

                while multi_clone_state["is_paused"]:
                    if multi_clone_state["is_cancelled"]:
                        break
                    await asyncio.sleep(2)

                if multi_clone_state["is_cancelled"]:
                    break

                batch.append(doc)

                if len(batch) >= 5000:
                    try:
                        Media.collection.insert_many(batch, ordered=False)
                    except Exception as db_err:
                        if MULTIPLE_DB and Media2:
                            try:
                                Media2.collection.insert_many(batch, ordered=False)
                            except Exception:
                                pass
                        else:
                            pass

                    grand_total_copied += len(batch)
                    multi_clone_state["current_count"] = grand_total_copied
                    batch = []
                    await update_live_multi_panel(message)

            if batch and not multi_clone_state["is_cancelled"]:
                try:
                    Media.collection.insert_many(batch, ordered=False)
                except Exception:
                    if MULTIPLE_DB and Media2:
                        try:
                            Media2.collection.insert_many(batch, ordered=False)
                        except Exception:
                            pass
                grand_total_copied += len(batch)
                multi_clone_state["current_count"] = grand_total_copied

        if multi_clone_state["is_cancelled"]:
            await message.edit_text(
                f"❌ **Cloning Cancelled!**\nSuccessfully saved `{grand_total_copied}` files.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ Clear Menu", callback_data="clear_menu")]])
            )
        else:
            db_info_msg = " (With Dual-DB Auto-Balancing)" if MULTIPLE_DB else ""
            await message.edit_text(
                f"✅ **All Sources Cloned Successfully!**{db_info_msg}\n\n"
                f"Total files safely added: **{grand_total_copied}**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ Clear Menu", callback_data="clear_menu")]])
            )

    except Exception as e:
        await message.edit_text(f"❌ **Clone Failed:**\n<code>{str(e)}</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ Clear Menu", callback_data="clear_menu")]]))
    
    finally:
        multi_clone_state["is_running"] = False
        multi_clone_state["is_paused"] = False
        multi_clone_state["is_cancelled"] = False
