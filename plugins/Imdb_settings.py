from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
# Import your database helper functions for settings (adjust imports based on your bot structure)
from database.connections_mdb import save_group_settings, get_settings


@Client.on_callback_query(filters.regex(r'^imdb_menu#') | filters.regex(r'^toggle_imdb_poster#'))
async def imdb_settings_callback(client: Client, query: CallbackQuery):
    data = query.data.split("#")
    action = data[0]
    grp_id = int(data[1])

    # Fetch current group settings from DB
    settings = await get_settings(grp_id)
    poster_status = settings.get("imdb", False)

    # If the user clicked the toggle button (On Poster / Off Poster)
    if action == "toggle_imdb_poster":
        poster_status = not poster_status
        await save_group_settings(grp_id, "imdb", poster_status)
        await query.answer("IMDb Poster status updated!")

    # Format status text
    status_text = "ᴏɴ ✅" if poster_status else "ᴏꜰꜰ ❌"
    button_text = "OFF POSTER ❌" if poster_status else "ON POSTER 🟢"

    # Message text layout
    message_text = (
        "ʜᴇʀᴇ ʏᴏᴜ ᴄᴀɴ ᴍᴀɴᴀɢᴇ ʏᴏᴜʀ ɢʀᴏᴜᴘ ɪᴍᴅʙ sᴇᴛᴛɪɴɢ.\n\n"
        f"ɪᴍᴅʙ ᴘᴏsᴛᴇʀ - {status_text}\n\n"
        "ɪᴍᴅʙ ᴛᴇᴍᴘʟᴀᴛᴇ -\n\n"
        "🏷 ᴛɪᴛʟᴇ - {search}\n\n"
        "📢 ʀᴇǫᴜᴇꜱᴛᴇᴅ ʙʏ - {mention}\n"
        "♾️ ᴘᴏᴡᴇʀᴇᴅ ʙʏ - {group}"
    )

    # Sub-menu button layout
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(button_text, callback_data=f"toggle_imdb_poster#{grp_id}")
        ],
        [
            InlineKeyboardButton("« ʙᴀᴄᴋ", callback_data=f"option_setgs#{grp_id}")
        ]
    ])

    # Edit the message with updated status and buttons
    await query.message.edit_text(
        text=message_text,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )
