import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, MessageNotModified
from utils import get_settings, save_group_settings, is_check_admin
from logging_helper import LOGGER

@Client.on_callback_query(filters.regex(r'^auto_delete_menu'))
async def auto_delete_menu_handler(client, query):
    _, grp_id = query.data.split("#")
    user_id = query.from_user.id if query.from_user else None
    
    if not await is_check_admin(client, int(grp_id), user_id):
        return await query.answer("<b>ɴᴇᴇᴅ ᴛᴏ ʙᴇ ᴀᴅᴍɪɴ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ✅.</b>", show_alert=True)

    settings = await get_settings(int(grp_id))
    auto_delete_status = settings.get("auto_delete", False)
    auto_del_time = settings.get("auto_del_time", 300) # Default to 300s or whatever your base config is
    status_text = "ᴇɴᴀʙʟᴇᴅ ✅" if auto_delete_status else "ᴅɪꜱᴀʙʟᴇᴅ ❌"

    btn = [
        [
            InlineKeyboardButton(
                "ᴛᴜʀɴ ᴏꜰꜰ ❌" if auto_delete_status else "ᴛᴜʀɴ ᴏɴ ✅", 
                callback_data=f'toggle_auto_delete#{auto_delete_status}#{grp_id}'
            )
        ],
        [
            InlineKeyboardButton(f"⏱️ ᴛɪᴍᴇ: {auto_del_time}s", callback_data=f'change_autodel_time#{grp_id}')
        ],
        [
            InlineKeyboardButton("<< ʙᴀᴄᴋ", callback_data=f'grp_pm#{grp_id}')
        ]
    ]

    text = (
        "<b>🗑️ ᴀᴜᴛᴏ ᴅᴇʟᴇᴛᴇ ꜱᴇᴛᴛɪɴɢꜱ\n\n"
        "ɪꜰ ᴀᴜᴛᴏ ᴅᴇʟᴇᴛᴇ ɪꜱ ᴇɴᴀʙʟᴇᴅ, ꜱᴇɴᴛ ꜰɪʟᴇꜱ/ᴍᴇꜱꜱᴀɢᴇꜱ "
        "ᴡɪʟʟ ʙᴇ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ ᴅᴇʟᴇᴛᴇᴅ ᴀꜰᴛᴇʀ ᴀ ꜱᴘᴇᴄɪꜰɪᴇᴅ ᴛɪᴍᴇ.\n\n"
        f"ᴄᴜʀʀᴇɴᴛ ꜱᴛᴀᴛᴜꜱ: {status_text}\n"
        f"ᴅᴇʟᴇᴛᴇ ᴛɪᴍᴇ: <code>{auto_del_time} ꜱᴇᴄᴏɴᴅꜱ</code></b>"
    )

    try:
        await query.message.edit(text, reply_markup=InlineKeyboardMarkup(btn))
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await query.message.edit(text, reply_markup=InlineKeyboardMarkup(btn))
    except MessageNotModified:
        pass


@Client.on_callback_query(filters.regex(r'^toggle_auto_delete'))
async def toggle_auto_delete_handler(client, query):
    _, current_status, grp_id = query.data.split("#")
    user_id = query.from_user.id if query.from_user else None
    
    if not await is_check_admin(client, int(grp_id), user_id):
        return await query.answer("<b>ɴᴇᴇᴅ ᴛᴏ ʙᴇ ᴀᴅᴍɪɴ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ✅.</b>", show_alert=True)

    new_status = not (current_status == "True")
    await save_group_settings(int(grp_id), "auto_delete", new_status)
    
    await query.answer(f"ᴀᴜᴛᴏ ᴅᴇʟᴇᴛᴇ ꜱᴇᴛ ᴛᴏ {'ᴇɴᴀʙʟᴇᴅ' if new_status else 'ᴅɪꜱᴀʙʟᴇᴅ'} ✅", show_alert=True)
    
    query.data = f'auto_delete_menu#{grp_id}'
    await auto_delete_menu_handler(client, query)


@Client.on_callback_query(filters.regex(r'^change_autodel_time'))
async def change_autodel_time_handler(client, query):
    _, grp_id = query.data.split("#")
    user_id = query.from_user.id if query.from_user else None
    
    if not await is_check_admin(client, int(grp_id), user_id):
        return await query.answer("<b>ɴᴇᴇᴅ ᴛᴏ ʙᴇ ᴀᴅᴍɪɴ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ✅.</b>", show_alert=True)

    try:
        await query.message.edit(
            "<b>⏱️ ꜱᴇɴᴅ ɴᴇᴡ ᴀᴜᴛᴏ ᴅᴇʟᴇᴛᴇ ᴛɪᴍᴇ ɪɴ ꜱᴇᴄᴏɴᴅꜱ (ᴇxᴀᴍᴘʟᴇ: 60, 120, 300)\n\n"
            "ᴏʀ ᴜꜱᴇ <code>/cancel</code> ᴛᴏ ᴄᴀɴᴄᴇʟ.</b>"
        )
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await query.message.edit("<b>⏱️ ꜱᴇɴᴅ ɴᴇᴡ ᴀᴜᴛᴏ ᴅᴇʟᴇᴛᴇ ᴛɪᴍᴇ ɪɴ ꜱᴇᴄᴏɴᴅꜱ...</b>")

    while True:
        time_msg = await client.listen(chat_id=query.message.chat.id, user_id=user_id)
        if time_msg.text == "/cancel":
            await time_msg.delete()
            query.data = f'auto_delete_menu#{grp_id}'
            await auto_delete_menu_handler(client, query)
            return
            
        if time_msg.text.isdigit() and int(time_msg.text) > 0:
            new_time = int(time_msg.text)
            break
        else:
            await query.message.reply("<b>⚠️ ɪɴᴠᴀʟɪᴅ ᴛɪᴍᴇ! ᴘʟᴇᴀꜱᴇ ꜱᴇɴᴅ ᴀ ᴘᴏꜱɪᴛɪᴠᴇ ɴᴜᴍʙᴇʀ (ᴇ.ɢ. 60).</b>")

    await time_msg.delete()
    await save_group_settings(int(grp_id), "auto_del_time", new_time)
    
    query.data = f'auto_delete_menu#{grp_id}'
    await auto_delete_menu_handler(client, query)
