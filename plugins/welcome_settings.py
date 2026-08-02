import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, MessageNotModified
from utils import get_settings, save_group_settings, is_check_admin
from logging_helper import LOGGER

@Client.on_callback_query(filters.regex(r'^welcome_menu'))
async def welcome_menu_handler(client, query):
    _, grp_id = query.data.split("#")
    user_id = query.from_user.id if query.from_user else None
    
    # Check if user is group admin
    if not await is_check_admin(client, int(grp_id), user_id):
        return await query.answer("<b>ɴᴇᴇᴅ ᴛᴏ ʙᴇ ᴀᴅᴍɪɴ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ✅.</b>", show_alert=True)

    settings = await get_settings(int(grp_id))
    welcome_status = settings.get("welcome", False)
    status_text = "ᴇɴᴀʙʟᴇᴅ ✅" if welcome_status else "ᴅɪꜱᴀʙʟᴇᴅ ❌"

    btn = [
        [
            InlineKeyboardButton(
                "ᴛᴜʀɴ ᴏꜰꜰ ❌" if welcome_status else "ᴛᴜʀɴ ᴏɴ ✅", 
                callback_data=f'toggle_welcome#{welcome_status}#{grp_id}'
            )
        ],
        [
            InlineKeyboardButton("<< ʙᴀᴄᴋ", callback_data=f'grp_pm#{grp_id}')
        ]
    ]

    text = (
        "<b>👋 ᴡᴇʟᴄᴏᴍᴇ ᴍꜱɢ ꜱᴇᴛᴛɪɴɢꜱ\n\n"
        "ɪꜰ ᴡᴇʟᴄᴏᴍᴇ ᴍꜱɢ ɪꜱ ᴇɴᴀʙʟᴇᴅ, ᴛʜᴇ ʙᴏᴛ ᴡɪʟʟ "
        "ꜱᴇɴᴅ ᴀ ᴡᴇʟᴄᴏᴍᴇ ᴍᴇꜱꜱᴀɢᴇ ᴡʜᴇɴ ɴᴇᴡ ᴍᴇᴍʙᴇʀꜱ ᴊᴏɪɴ ᴛʜᴇ ɢʀᴏᴜᴘ.\n\n"
        f"ᴄᴜʀʀᴇɴᴛ ꜱᴛᴀᴛᴜꜱ: {status_text}</b>"
    )

    try:
        await query.message.edit(text, reply_markup=InlineKeyboardMarkup(btn))
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await query.message.edit(text, reply_markup=InlineKeyboardMarkup(btn))
    except MessageNotModified:
        pass


@Client.on_callback_query(filters.regex(r'^toggle_welcome'))
async def toggle_welcome_handler(client, query):
    _, current_status, grp_id = query.data.split("#")
    user_id = query.from_user.id if query.from_user else None
    
    if not await is_check_admin(client, int(grp_id), user_id):
        return await query.answer("<b>ɴᴇᴇᴅ ᴛᴏ ʙᴇ ᴀᴅᴍɪɴ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ✅.</b>", show_alert=True)

    # Flip the boolean state
    new_status = not (current_status == "True")
    await save_group_settings(int(grp_id), "welcome", new_status)
    
    await query.answer(f"ᴡᴇʟᴄᴏᴍᴇ ᴍꜱɢ ꜱᴇᴛ ᴛᴏ {'ᴇɴᴀʙʟᴇᴅ' if new_status else 'ᴅɪꜱᴀʙʟᴇᴅ'} ✅", show_alert=True)
    
    # Refresh the welcome menu
    query.data = f'welcome_menu#{grp_id}'
    await welcome_menu_handler(client, query)
