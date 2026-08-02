import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, MessageNotModified
from utils import get_settings, save_group_settings, is_check_admin
from logging_helper import LOGGER

@Client.on_callback_query(filters.regex(r'^file_secure_menu'))
async def file_secure_menu_handler(client, query):
    _, grp_id = query.data.split("#")
    user_id = query.from_user.id if query.from_user else None
    
    # Check if the user is an admin
    if not await is_check_admin(client, int(grp_id), user_id):
        return await query.answer("<b>ɴᴇᴇْد ᴛᴏ ʙᴇ ᴀᴅᴍɪɴ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ✅.</b>", show_alert=True)

    settings = await get_settings(int(grp_id))
    file_secure_status = settings.get("file_secure", False)
    status_text = "ᴇɴᴀʙʟᴇᴅ ✅" if file_secure_status else "ᴅɪꜱᴀʙʟᴇᴅ ❌"

    btn = [
        [
            InlineKeyboardButton(
                "ᴛᴜʀɴ ᴏꜰꜰ ❌" if file_secure_status else "ᴛᴜʀɴ ᴏɴ ✅", 
                callback_data=f'toggle_file_secure#{file_secure_status}#{grp_id}'
            )
        ],
        [
            InlineKeyboardButton("<< ʙᴀᴄᴋ", callback_data=f'grp_pm#{grp_id}')
        ]
    ]

    text = (
        "<b>🗂 ꜰɪʟᴇꜱ ꜱᴇᴄᴜʀᴇ ꜱᴇᴛᴛɪɴɢꜱ\n\n"
        "ɪꜰ ꜰɪʟᴇꜱ ꜱᴇᴄᴜʀᴇ ɪꜱ ᴇɴᴀʙʟᴇᴅ, ᴜꜱᴇʀꜱ ᴄᴀɴɴᴏᴛ "
        "ꜰᴏʀᴡᴀʀᴅ ᴏʀ ꜱᴀᴠᴇ ꜰɪʟᴇꜱ ꜰʀᴏᴍ ʏᴏᴜʀ ʙᴏᴛ.\n\n"
        f"ᴄᴜʀʀᴇɴᴛ ꜱᴛᴀᴛᴜꜱ: {status_text}</b>"
    )

    try:
        await query.message.edit(text, reply_markup=InlineKeyboardMarkup(btn))
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await query.message.edit(text, reply_markup=InlineKeyboardMarkup(btn))
    except MessageNotModified:
        pass


@Client.on_callback_query(filters.regex(r'^toggle_file_secure'))
async def toggle_file_secure_handler(client, query):
    _, current_status, grp_id = query.data.split("#")
    user_id = query.from_user.id if query.from_user else None
    
    if not await is_check_admin(client, int(grp_id), user_id):
        return await query.answer("<b>ɴᴇᴇᴅ ᴛᴏ ʙᴇ ᴀᴅᴍɪɴ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ✅.</b>", show_alert=True)

    # Flip the boolean state
    new_status = not (current_status == "True")
    await save_group_settings(int(grp_id), "file_secure", new_status)
    
    await query.answer(f"ꜰɪʟᴇꜱ ꜱᴇᴄᴜʀᴇ ꜱᴇᴛ ᴛᴏ {'ᴇɴᴀʙʟᴇᴅ' if new_status else 'ᴅɪꜱᴀʙʟᴇᴅ'} ✅", show_alert=True)
    
    # Refresh the menu by updating the callback data and calling the menu function again
    query.data = f'file_secure_menu#{grp_id}'
    await file_secure_menu_handler(client, query)
