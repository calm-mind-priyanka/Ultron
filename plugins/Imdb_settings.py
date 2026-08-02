import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import MessageNotModified, FloodWait
from utils import get_settings, save_group_settings, is_check_admin


@Client.on_callback_query(filters.regex(r'^(imdb_menu|toggle_imdb_poster)#'))
async def imdb_settings_callback(client: Client, query: CallbackQuery):
    data = query.data.split("#")
    action = data[0]
    grp_id = int(data[1])
    user_id = query.from_user.id if query.from_user else None

    # Check admin rights matching your other settings callbacks
    if not await is_check_admin(client, grp_id, user_id):
        return await query.answer("<b>ɴᴇᴇᴅ ᴛᴏ ʙᴇ ᴀᴅᴍɪɴ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ✅.</b>", show_alert=True)

    # Fetch current group settings from DB
    settings = await get_settings(grp_id)
    poster_status = settings.get("imdb", False)

    # Toggle IMDb poster setting if requested
    if action == "toggle_imdb_poster":
        poster_status = not poster_status
        await save_group_settings(grp_id, "imdb", poster_status)
        await query.answer("ɪᴍᴅʙ ᴘᴏsᴛᴇʀ sᴛᴀᴛᴜs ᴜᴘᴅᴀᴛᴇᴅ! ✅")

    # Format status text & toggle button text
    status_text = "ᴏɴ ✅" if poster_status else "ᴏꜰꜰ ❌"
    button_text = "OFF POSTER ❌" if poster_status else "ON POSTER 🟢"

    # Settings Layout Message
    message_text = (
        "<b>⚙️ ɪᴍᴅʙ sᴇᴛᴛɪɴɢs\n\n"
        "ʜᴇʀᴇ ʏᴏᴜ ᴄᴀɴ ᴍᴀɴᴀɢᴇ ʏᴏᴜʀ ɢʀᴏᴜᴘ ɪᴍᴅʙ sᴇᴛᴛɪɴɢ.\n\n"
        f"ɪᴍᴅʙ ᴘᴏsᴛᴇʀ : {status_text}\n\n"
        "ɪᴍᴅʙ ᴛᴇᴍᴘʟᴀᴛᴇ :\n"
        "🏷 ᴛɪᴛʟᴇ - <code>{{search}}</code>\n"
        "📢 ʀᴇǫᴜᴇꜱᴛᴇᴅ ʙʏ - <code>{{mention}}</code>\n"
        "♾️ ᴘᴏᴡᴇʀᴇᴅ ʙʏ - <code>{{group}}</code></b>"
    )

    # Keyboard Layout
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(button_text, callback_data=f"toggle_imdb_poster#{grp_id}")
        ],
        [
            InlineKeyboardButton("« ʙᴀᴄᴋ", callback_data=f"grp_pm#{grp_id}")
        ]
    ])

    # Edit message with error handling for Pyrogram
    try:
        await query.message.edit_text(
            text=message_text,
            reply_markup=keyboard,
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML
        )
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await query.message.edit_text(
            text=message_text,
            reply_markup=keyboard,
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML
        )
    except MessageNotModified:
        pass
