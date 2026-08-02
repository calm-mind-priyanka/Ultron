import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import MessageNotModified, FloodWait
from utils import get_settings, save_group_settings, is_check_admin

@Client.on_callback_query(filters.regex(r'^result_mode_setgs'))
async def result_mode_settings(client, query):
    grp_id = query.data.split("#")[-1]
    user_id = query.from_user.id if query.from_user else None
    if not await is_check_admin(client, int(grp_id), user_id):
        return await query.answer("<b>ɴᴇᴇᴅ ᴛᴏ ʙᴇ ᴀᴅᴍɪɴ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ✅.</b>", show_alert=True)

    settings = await get_settings(int(grp_id))
    button_mode = settings.get('button', False)  # True = buttons, False = links
    mode_text = "ʙᴜᴛᴛᴏɴꜱ 🎯" if button_mode else "ʟɪɴᴋꜱ 🖇"
    toggle_btn_text = "ꜱᴇᴛ ʟɪɴᴋꜱ ᴍᴏᴅᴇ" if button_mode else "ꜱᴇᴛ ʙᴜᴛᴛᴏɴ ᴍᴏᴅᴇ"

    btn = [[
        InlineKeyboardButton(toggle_btn_text, callback_data=f'toggleresultmode#{button_mode}#{grp_id}'),
    ],[
        InlineKeyboardButton('<< ʙᴀᴄᴋ', callback_data=f'grp_pm#{grp_id}')
    ]]

    text = (
        "<b>ʜᴇʀᴇ ʏᴏᴜ ᴄᴀɴ ᴍᴀɴᴀɢᴇ ʏᴏᴜʀ ɢʀᴏᴜᴘ ɢɪᴠᴇɴ ʀᴇꜱᴜʟᴛ ᴍᴏᴅᴇ.\n\n"
        f"ʀᴇꜱᴜʟᴛ ᴍᴏᴅᴇ - {mode_text}</b>"
    )

    try:
        await query.message.edit(text, reply_markup=InlineKeyboardMarkup(btn), parse_mode=enums.ParseMode.HTML)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await query.message.edit(text, reply_markup=InlineKeyboardMarkup(btn), parse_mode=enums.ParseMode.HTML)
    except MessageNotModified:
        pass

@Client.on_callback_query(filters.regex(r'^toggleresultmode'))
async def toggle_result_mode(client, query):
    _, status, grp_id = query.data.split("#")
    user_id = query.from_user.id if query.from_user else None
    if not await is_check_admin(client, int(grp_id), user_id):
        return await query.answer("<b>ɴᴇᴇᴅ ᴛᴏ ʙᴇ ᴀᴅᴍɪɴ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ✅.</b>", show_alert=True)
    
    new_status = not (status == "True")
    await save_group_settings(int(grp_id), 'button', new_status)
    await query.answer("ʀᴇꜱᴜʟᴛ ᴍᴏᴅᴇ ᴜᴘᴅᴀᴛᴇᴅ ✅", show_alert=True)
    
    # Refresh the menu view
    query.data = f'result_mode_setgs#{grp_id}'
    await result_mode_settings(client, query)
