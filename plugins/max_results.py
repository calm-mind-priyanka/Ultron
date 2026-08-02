import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import MessageNotModified, FloodWait
from info import *
from utils import get_settings, save_group_settings, MAX_B_TN, is_check_admin

@Client.on_callback_query(filters.regex(r'^max_result_menu'))
async def max_result_menu_handler(client, query):
    _, grp_id = query.data.split("#")
    user_id = query.from_user.id if query.from_user else None
    
    if not await is_check_admin(client, int(grp_id), user_id):
        return await query.answer("<b>ɴᴇᴇᴅ ᴛᴏ ʙᴇ ᴀᴅᴍɪɴ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ✅.</b>", show_alert=True)

    settings = await get_settings(int(grp_id))
    max_btn = settings.get("max_btn", False)
    
    # Text status representation
    status_text = "10" if max_btn else f"{MAX_B_TN} (Default)"

    text = (
        "<b>ℹ️ ᴍᴀx ʀᴇꜱᴜʟᴛꜱ ꜱᴇᴛᴛɪɴɢꜱ\n\n"
        "ʜᴇʀᴇ ʏᴏᴜ ᴄᴀɴ ᴄʜᴀɴɢᴇ ᴛʜᴇ ᴍᴀxɪᴍᴜᴍ ʀᴇꜱᴜʟᴛꜱ / ʙᴜᴛᴛᴏɴꜱ "
        "ᴅɪꜱᴘʟᴀʏᴇᴅ ᴘᴇʀ ᴘᴀɢᴇ ɪɴ ꜱᴇᴀʀᴄʜ.\n\n"
        f"ᴄᴜʀʀᴇɴᴛ ᴍᴀx ʙᴜᴛᴛᴏɴꜱ: <code>{status_text}</code></b>"
    )

    btn = [
        [
            InlineKeyboardButton(
                '✅ 10' if max_btn else '10', 
                callback_data=f'setgs#max_btn#True#{grp_id}'
            ),
            InlineKeyboardButton(
                f'✅ {MAX_B_TN}' if not max_btn else f'{MAX_B_TN}', 
                callback_data=f'setgs#max_btn#False#{grp_id}'
            )
        ],
        [
            InlineKeyboardButton('<< ʙᴀᴄᴋ', callback_data=f'grp_pm#{grp_id}')
        ]
    ]

    try:
        await query.message.edit(text, reply_markup=InlineKeyboardMarkup(btn))
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await query.message.edit(text, reply_markup=InlineKeyboardMarkup(btn))
    except MessageNotModified:
        pass
