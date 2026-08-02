import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, MessageNotModified
from utils import get_settings, save_group_settings, is_check_admin

@Client.on_callback_query(filters.regex(r'^max_result_menu'))
async def max_result_menu_handler(client, query):
    _, grp_id = query.data.split("#")
    user_id = query.from_user.id if query.from_user else None
    
    if not await is_check_admin(client, int(grp_id), user_id):
        return await query.answer("<b>ɴᴇᴇᴅ ᴛᴏ ʙᴇ ᴀᴅᴍɪɴ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ✅.</b>", show_alert=True)

    settings = await get_settings(int(grp_id))
    current_max = int(settings.get("max_btn", 10))

    btn_8_text = "✅ 8 Results" if current_max == 8 else "8 Results"
    btn_10_text = "✅ 10 Results" if current_max == 10 else "10 Results"

    btn = [
        [
            InlineKeyboardButton(btn_8_text, callback_data=f'set_max_val#8#{grp_id}'),
            InlineKeyboardButton(btn_10_text, callback_data=f'set_max_val#10#{grp_id}')
        ],
        [
            InlineKeyboardButton("<< ʙᴀᴄᴋ", callback_data=f'grp_pm#{grp_id}')
        ]
    ]

    text = (
        "<b>ℹ️ ᴍᴀx ʀᴇꜱᴜʟᴛꜱ ꜱᴇᴛᴛɪɴɢꜱ\n\n"
        "ᴄʜᴏᴏꜱᴇ ʜᴏᴡ ᴍᴀɴʏ ʀᴇꜱᴜʟᴛꜱ (ʙᴜᴛᴛᴏɴꜱ) ᴛʜᴇ ʙᴏᴛ ꜱʜᴏᴜʟᴅ "
        "ꜱʜᴏᴡ ᴡʜᴇɴ ᴀ ᴜꜱᴇʀ ꜱᴇᴀʀᴄʜᴇꜱ ꜰᴏʀ ᴀ ᴍᴏᴠɪᴇ/ꜰɪʟᴇ.\n\n"
        f"ᴄᴜʀʀᴇɴᴛ ꜱᴇʟᴇᴄᴛɪᴏɴ: <code>{current_max}</code>\n\n"
        "<i>ᴄʟɪᴄᴋ ᴀɴ ᴏᴘᴛɪᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ꜱᴇᴛ ɪᴛ.</i></b>"
    )

    try:
        await query.message.edit(text, reply_markup=InlineKeyboardMarkup(btn))
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await query.message.edit(text, reply_markup=InlineKeyboardMarkup(btn))
    except MessageNotModified:
        pass


@Client.on_callback_query(filters.regex(r'^set_max_val'))
async def set_max_val_handler(client, query):
    _, val, grp_id = query.data.split("#")
    user_id = query.from_user.id if query.from_user else None
    
    if not await is_check_admin(client, int(grp_id), user_id):
        return await query.answer("<b>ɴᴇᴇᴅ ᴛᴏ ʙᴇ ᴀᴅᴍɪɴ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ✅.</b>", show_alert=True)

    new_val = int(val)
    await save_group_settings(int(grp_id), "max_btn", new_val)
    await query.answer(f"ᴍᴀx ʀᴇꜱᴜʟᴛꜱ ꜱᴇᴛ ᴛᴏ {new_val} ✅", show_alert=True)
    
    query.data = f'max_result_menu#{grp_id}'
    await max_result_menu_handler(client, query)
