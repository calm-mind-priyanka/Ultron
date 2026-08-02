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
    current_max = settings.get("max_btn", MAX_B_TN)
    
    text = (
        "<b>ℹ️ ᴍᴀx ʀᴇꜱᴜʟᴛꜱ ꜱᴇᴛᴛɪɴɢꜱ\n\n"
        "ʜᴇʀᴇ ʏᴏᴜ ᴄᴀɴ ᴄʜᴀɴɢᴇ ᴛʜᴇ ᴍᴀxɪᴍᴜᴍ ʀᴇꜱᴜʟᴛꜱ / ʙᴜᴛᴛᴏɴꜱ "
        "ᴅɪꜱᴘʟᴀʏᴇᴅ ᴘᴇʀ ᴘᴀɢᴇ ɪɴ ꜱᴇᴀʀᴄʜ.\n\n"
        f"ᴄᴜʀʀᴇɴᴛ ᴍᴀx ʙᴜᴛᴛᴏɴꜱ: <code>{current_max}</code></b>"
    )

    # Dynamic checkmarks depending on active setting
    btn_8 = '✅ 8' if str(current_max) == '8' else '8'
    btn_10 = '✅ 10' if str(current_max) == '10' else '10'
    btn_def = f'✅ {MAX_B_TN} (Default)' if str(current_max) == str(MAX_B_TN) else f'{MAX_B_TN} (Default)'

    btn = [
        [
            InlineKeyboardButton(btn_8, callback_data=f'setgs#max_btn#8#{grp_id}'),
            InlineKeyboardButton(btn_10, callback_data=f'setgs#max_btn#10#{grp_id}'),
        ],
        [
            InlineKeyboardButton(btn_def, callback_data=f'setgs#max_btn#{MAX_B_TN}#{grp_id}')
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


@Client.on_callback_query(filters.regex(r'^setgs#max_btn'))
async def set_max_results_handler(client, query):
    # Parses format: setgs#max_btn#VALUE#GRP_ID
    _, _, val, grp_id = query.data.split("#")
    userid = query.from_user.id if query.from_user else None
    
    if not await is_check_admin(client, int(grp_id), userid):
        return await query.answer("<b>ɴᴇᴇᴅ ᴛᴏ ʙᴇ ᴀᴅᴍɪɴ ᴛᴏ ᴜꜱᴇ ᴛʜɪꜱ ✅.</b>", show_alert=True)

    # Save the selected numeric choice into database
    try:
        final_val = int(val)
    except ValueError:
        final_val = val

    await save_group_settings(int(grp_id), "max_btn", final_val)
    await query.answer(f"Max Results set to {final_val} ✓")

    # Refresh the max results menu UI
    settings = await get_settings(int(grp_id))
    current_max = settings.get("max_btn", MAX_B_TN)

    text = (
        "<b>ℹ️ ᴍᴀx ʀᴇꜱᴜʟᴛꜱ ꜱᴇᴛᴛɪɴɢꜱ\n\n"
        "ʜᴇʀᴇ ʏᴏᴜ ᴄᴀɴ ᴄʜᴀɴɢᴇ ᴛʜᴇ ᴍᴀxɪᴍᴜᴍ ʀᴇꜱᴜʟᴛꜱ / ʙᴜᴛᴛᴏɴꜱ "
        "ᴅɪꜱᴘʟᴀʏᴇᴅ ᴘᴇʀ ᴘᴀɢᴇ ɪɴ ꜱᴇᴀʀᴄʜ.\n\n"
        f"ᴄᴜʀʀᴇɴᴛ ᴍᴀx ʙᴜᴛᴛᴏɴꜱ: <code>{current_max}</code></b>"
    )

    btn_8 = '✅ 8' if str(current_max) == '8' else '8'
    btn_10 = '✅ 10' if str(current_max) == '10' else '10'
    btn_def = f'✅ {MAX_B_TN} (Default)' if str(current_max) == str(MAX_B_TN) else f'{MAX_B_TN} (Default)'

    btn = [
        [
            InlineKeyboardButton(btn_8, callback_data=f'setgs#max_btn#8#{grp_id}'),
            InlineKeyboardButton(btn_10, callback_data=f'setgs#max_btn#10#{grp_id}'),
        ],
        [
            InlineKeyboardButton(btn_def, callback_data=f'setgs#max_btn#{MAX_B_TN}#{grp_id}')
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
