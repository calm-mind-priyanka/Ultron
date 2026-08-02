import asyncio
import datetime
from datetime import timedelta, timezone
import time
import pytz

from pyrogram import Client, filters
from pyrogram.errors.exceptions.bad_request_400 import MessageTooLong
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    PreCheckoutQuery,
)

from database.users_chats_db import db
from info import *
from logging_helper import LOGGER
from Script import script
from utils import get_seconds, temp


def format_expiry(expiry):
    """Safely converts UTC naive/aware datetime from database into IST string and datetime."""
    if not expiry:
        return None, "N/A"

    # If datetime is naive (from MongoDB), attach UTC timezone first
    if expiry.tzinfo is None:
        expiry = pytz.utc.localize(expiry)

    expiry_ist = expiry.astimezone(pytz.timezone("Asia/Kolkata"))
    expiry_str = expiry_ist.strftime("%d-%m-%Y\n⏱️ ᴇxᴘɪʀʏ ᴛɪᴍᴇ : %I:%M:%S %p")
    return expiry_ist, expiry_str


@Client.on_message(filters.command("remove_premium") & filters.user(ADMINS))
async def remove_premium(client, message):
    if len(message.command) == 2:
        try:
            user_id = int(message.command[1])
            user = await client.get_users(user_id)
            if await db.remove_premium_access(user_id):
                await message.reply_text("ᴜꜱᴇʀ ʀᴇᴍᴏᴠᴇᴅ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ !")
                try:
                    await client.send_message(
                        chat_id=user_id,
                        text=(
                            f"<b>ʜᴇʏ {user.mention},\n\n"
                            "𝒀𝒐𝒖𝒓 𝑷𝒓𝒆𝒎𝒊𝒖𝒎 𝑨𝒄𝒄𝒆𝒔𝒔 𝑯𝒂𝒔 𝑩𝒆𝒆𝒏 𝑹𝒆𝒎𝒐𝒗𝒆𝒅. "
                            "𝑻𝒉𝒂𝒏𝒌 𝑶𝒖 𝑭𝒐𝒓 𝑼𝒔𝒊𝒏𝒈 𝑶𝒖𝒓 𝑺𝒆𝒓𝒗𝒊𝒄𝒆 😊. "
                            "𝑪𝒍𝒊𝒄𝒌 𝑶𝒏 /plan 𝑻𝒐 𝑪𝒉𝒆𝒄𝒌 𝑶𝒕𝒉𝒆𝒓 𝑷𝒍𝒂𝒏𝒔.\n\n"
                            "<blockquote>आपका Premium Access हटा दिया गया है। हमारी सेवा का उपयोग करने के लिए धन्यवाद 🥳 "
                            "हमारी अन्य योजनाओं की जाँच करने के लिए /plan पर क्लिक करें ।</blockquote></b>"
                        ),
                    )
                except Exception:
                    pass
            else:
                await message.reply_text("ᴜɴᴀʙʟᴇ ᴛᴏ ʀᴇᴍᴏᴠᴇ ᴜꜱᴇʀ !\nᴀʀᴇ ʏᴏᴜ ꜱᴜʀᴇ, ɪᴛ ᴡᴀꜱ ᴀ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀ ɪᴅ ?")
        except Exception as e:
            await message.reply_text(f"Error: {e}")
    else:
        await message.reply_text("ᴜꜱᴀɢᴇ : /remove_premium user_id")


@Client.on_message(filters.command("myplan"))
async def myplan(client, message):
    try:
        user = message.from_user.mention
        user_id = message.from_user.id
        data = await db.get_user(user_id)

        if data and data.get("expiry_time"):
            expiry = data.get("expiry_time")
            expiry_ist, expiry_str_in_ist = format_expiry(expiry)

            if not expiry_ist:
                return await message.reply_text("Invalid plan expiration date stored.")

            current_time = datetime.datetime.now(pytz.timezone("Asia/Kolkata"))

            if expiry_ist <= current_time:
                await db.remove_premium_access(user_id)
                return await message.reply_text(
                    f"<b>ʜᴇʏ {user},\n\nʏᴏᴜʀ ᴘʀᴇᴍɪᴜᴍ ᴘʟᴀɴ ʜᴀꜱ ᴇxᴘɪʀᴇᴅ. ʙᴜʏ ᴏᴜʀ ꜱᴜʙꜱᴄʀɪᴘᴛɪᴏɴ ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ ᴘʀᴇᴍɪᴜᴍ ʙᴇɴᴇꜰɪᴛꜱ.</b>",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("• ᴄʜᴇᴄᴋᴏᴜᴛ ᴘʀᴇᴍɪᴜᴍ ᴘʟᴀɴꜱ •", callback_data="buy")]]
                    ),
                )

            time_left = expiry_ist - current_time
            days = time_left.days
            hours, remainder = divmod(time_left.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            time_left_str = f"{days} ᴅᴀʏꜱ, {hours} ʜᴏᴜʀꜱ, {minutes} ᴍɪɴᴜᴛᴇꜱ"
            await message.reply_text(
                f"⚜️ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀ ᴅᴀᴛᴀ :\n\n"
                f"👤 ᴜꜱᴇʀ : {user}\n"
                f"⚡ ᴜꜱᴇʀ ɪᴅ : <code>{user_id}</code>\n"
                f"⏰ ᴛɪᴍᴇ ʟᴇꜰᴛ : {time_left_str}\n"
                f"⌛️ ᴇxᴘɪʀʏ ᴅᴀᴛᴇ : {expiry_str_in_ist}"
            )
        else:
            await message.reply_text(
                f"<b>ʜᴇʏ {user},\n\nʏᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ ᴀɴ ᴀᴄᴛɪᴠᴇ ᴘʀᴇᴍɪᴜᴍ ᴘʟᴀɴ. ʙᴜʏ ᴏᴜʀ ꜱᴜʙꜱᴄʀɪᴘᴛɪᴏɴ ᴛᴏ ᴜꜱᴇ ᴘʀᴇᴍɪᴜᴍ ʙᴇɴᴇꜰɪᴛꜱ.</b>",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("• ᴄʜᴇᴄᴋᴏᴜᴛ ᴘʀᴇᴍɪᴜᴍ ᴘʟᴀɴꜱ •", callback_data="buy")]]
                ),
            )
    except Exception as e:
        LOGGER.error(f"Error in myplan: {e}")


@Client.on_message(filters.command("get_premium") & filters.user(ADMINS))
async def get_premium(client, message):
    if len(message.command) == 2:
        try:
            user_id = int(message.command[1])
            try:
                user = await client.get_users(user_id)
                mention = user.mention
            except Exception:
                mention = f"<code>{user_id}</code>"

            data = await db.get_user(user_id)
            if data and data.get("expiry_time"):
                expiry = data.get("expiry_time")
                expiry_ist, expiry_str_in_ist = format_expiry(expiry)

                if not expiry_ist:
                    return await message.reply_text("Invalid expiry timestamp in database.")

                current_time = datetime.datetime.now(pytz.timezone("Asia/Kolkata"))
                if expiry_ist <= current_time:
                    return await message.reply_text("⚠️ This user's premium subscription has already EXPIRED.")

                time_left = expiry_ist - current_time
                days = time_left.days
                hours, remainder = divmod(time_left.seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                time_left_str = f"{days} days, {hours} hours, {minutes} minutes"
                await message.reply_text(
                    f"⚜️ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀ ᴅᴀᴛᴀ :\n\n"
                    f"👤 ᴜꜱᴇʀ : {mention}\n"
                    f"⚡ ᴜꜱᴇʀ ɪᴅ : <code>{user_id}</code>\n"
                    f"⏰ ᴛɪᴍᴇ ʟᴇꜰᴛ : {time_left_str}\n"
                    f"⌛️ ᴇxᴘɪʀʏ ᴅᴀᴛᴇ : {expiry_str_in_ist}"
                )
            else:
                await message.reply_text("ɴᴏ ᴘʀᴇᴍɪᴜᴍ ᴅᴀᴛᴀ ꜰᴏᴜɴᴅ ɪɴ ᴅᴀᴛᴀʙᴀꜱᴇ !")
        except Exception as e:
            await message.reply_text(f"Error: {e}")
    else:
        await message.reply_text("ᴜꜱᴀɢᴇ : /get_premium user_id")


@Client.on_message(filters.command("add_premium") & filters.user(ADMINS))
async def give_premium_cmd_handler(client, message):
    if len(message.command) >= 3:
        time_zone = datetime.datetime.now(pytz.timezone("Asia/Kolkata"))
        current_time = time_zone.strftime("%d-%m-%Y\n⏱️ ᴊᴏɪɴɪɴɢ ᴛɪᴍᴇ : %I:%M:%S %p")
        try:
            user_id = int(message.command[1])
            user = await client.get_users(user_id)
            time_str = " ".join(message.command[2:])
            seconds = await get_seconds(time_str)
            if seconds > 0:
                # Store in UTC timezone awareness
                expiry_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
                user_data = {"id": user_id, "expiry_time": expiry_time}
                await db.update_user(user_data)

                _, expiry_str_in_ist = format_expiry(expiry_time)

                await message.reply_text(
                    f"ᴘʀᴇᴍɪᴜᴍ ᴀᴅᴅᴇᴅ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ✅\n\n"
                    f"👤 ᴜꜱᴇʀ : {user.mention}\n"
                    f"⚡ ᴜꜱᴇʀ ɪ繆 : <code>{user_id}</code>\n"
                    f"⏰ ᴘʀᴇᴍɪᴜᴍ ᴀᴄᴄᴇꜱꜱ : <code>{time_str}</code>\n\n"
                    f"⏳ ᴊᴏɪɴɪɴɢ ᴅᴀᴛᴇ : {current_time}\n\n"
                    f"⌛️ ᴇxᴘɪʀʏ ᴅᴀᴛᴇ : {expiry_str_in_ist}",
                    disable_web_page_preview=True,
                )

                try:
                    await client.send_message(
                        chat_id=user_id,
                        text=(
                            f"👋 ʜᴇʏ {user.mention},\n"
                            f"ᴛʜᴀɴᴋ ʏᴏᴜ ꜰᴏʀ ᴘᴜʀᴄʜᴀꜱɪɴɢ ᴘʀᴇᴍɪᴜᴍ.\n"
                            f"ᴇɴᴊᴏʏ !! ✨🎉\n\n"
                            f"⏰ ᴘʀᴇᴍɪᴜᴍ ᴀᴄᴄᴇꜱꜱ : <code>{time_str}</code>\n"
                            f"⏳ ᴊᴏɪɴɪɴɢ ᴅᴀᴛᴇ : {current_time}\n\n"
                            f"⌛️ ᴇxᴘɪʀʏ ᴅᴀᴛᴇ : {expiry_str_in_ist}"
                        ),
                        disable_web_page_preview=True,
                    )
                except Exception:
                    pass

                try:
                    await client.send_message(
                        PREMIUM_LOGS,
                        text=(
                            f"#Added_Premium\n\n"
                            f"👤 ᴜꜱᴇʀ : {user.mention}\n"
                            f"⚡ ᴜꜱᴇʀ ɪᴅ : <code>{user_id}</code>\n"
                            f"⏰ ᴘʀᴇᴍɪᴜᴍ ᴀᴄᴄᴇꜱꜱ : <code>{time_str}</code>\n\n"
                            f"⏳ ᴊᴏɪɴɪɴɢ ᴅᴀᴛᴇ : {current_time}\n\n"
                            f"⌛️ ᴇxᴘɪʀʏ ᴅᴀᴛᴇ : {expiry_str_in_ist}"
                        ),
                        disable_web_page_preview=True,
                    )
                except Exception:
                    pass
            else:
                await message.reply_text("Invalid time format. Example: `/add_premium 12345678 1 day` or `1 month`")
        except Exception as e:
            await message.reply_text(f"Error: {e}")
    else:
        await message.reply_text("Usage : /add_premium user_id time (e.g. '1 day', '1 month', '1 year')")


@Client.on_message(filters.command("premium_users") & filters.user(ADMINS))
async def premium_user(client, message):
    aa = await message.reply_text("<i>ꜰᴇᴛᴄʜɪɴɢ...</i>")
    new = " ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀꜱ ʟɪꜱᴛ :\n\n"
    user_count = 1

    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # Helper function to fetch premium users safely from a single DB collection
    async def fetch_from_col(users_collection):
        nonlocal new, user_count
        cursor = users_collection.find({"expiry_time": {"$gt": now_utc}})
        async for user_doc in cursor:
            expiry = user_doc.get("expiry_time")
            expiry_ist, expiry_str_in_ist = format_expiry(expiry)
            if not expiry_ist:
                continue

            current_time = datetime.datetime.now(pytz.timezone("Asia/Kolkata"))
            time_left = expiry_ist - current_time
            days = time_left.days
            hours, remainder = divmod(time_left.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            time_left_str = f"{days} days, {hours} hours, {minutes} minutes"

            uid = user_doc["id"]
            try:
                u_obj = await client.get_users(uid)
                mention = u_obj.mention
            except Exception:
                mention = f"User {uid}"

            new += f"{user_count}. {mention}\n👤 ᴜꜱᴇʀ ɪᴅ : <code>{uid}</code>\n⏳ ᴇxᴘɪʀʏ ᴅᴀᴛᴇ : {expiry_str_in_ist}\n⏰ ᴛɪᴍᴇ ʟᴇꜰᴛ : {time_left_str}\n\n"
            user_count += 1

    # Fetch from Primary DB
    try:
        await fetch_from_col(db.users)
    except Exception as e:
        LOGGER.error(f"Error fetching premium users from DB1: {e}")

    # Fetch from Secondary DB (if present)
    if hasattr(db, "users2"):
        try:
            await fetch_from_col(db.users2)
        except Exception as e:
            LOGGER.error(f"Error fetching premium users from DB2: {e}")

    if user_count == 1:
        return await aa.edit_text("<i>No active premium users found!</i>")

    try:
        await aa.edit_text(new)
    except MessageTooLong:
        with open("usersplan.txt", "w+") as outfile:
            outfile.write(new)
        await message.reply_document("usersplan.txt", caption="Paid Users:")


@Client.on_message(filters.command("plan"))
async def plan(client, message):
    user_id = message.from_user.id
    users = message.from_user.mention
    log_message = f"<b><u>🚫 ᴛʜɪs ᴜsᴇʀs ᴛʀʏ ᴛᴏ ᴄʜᴇᴄᴋ /plan</u> {temp.B_LINK}\n\n- ɪᴅ - `{user_id}`\n- ɴᴀᴍᴇ - {users}</b>"
    btn = [
        [
            InlineKeyboardButton("• ʙᴜʏ ᴘʀᴇᴍɪᴜᴍ •", callback_data="buy"),
        ],
        [
            InlineKeyboardButton("• ʀᴇꜰᴇʀ ꜰʀɪᴇɴᴅꜱ", callback_data="reffff"),
            InlineKeyboardButton("ꜰʀᴇᴇ ᴛʀɪᴀʟ •", callback_data="free"),
        ],
        [InlineKeyboardButton("🚫 ᴄʟᴏꜱᴇ 🚫", callback_data="close_data")],
    ]
    msg = await message.reply_photo(
        photo="https://graph.org/file/86da2027469565b5873d6.jpg",
        caption=script.BPREMIUM_TXT,
        reply_markup=InlineKeyboardMarkup(btn),
    )
    try:
        await client.send_message(PREMIUM_LOGS, log_message)
    except Exception:
        pass
    await asyncio.sleep(300)
    try:
        await msg.delete()
        await message.delete()
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"buy_\d+"))
async def premium_button(client, callback_query: CallbackQuery):
    try:
        amount = int(callback_query.data.split("_")[1])
        if amount in STAR_PREMIUM_PLANS:
            try:
                buttons = [[InlineKeyboardButton("ᴄᴀɴᴄᴇʟ 🚫", callback_data="cancel_star_premium")]]
                reply_markup = InlineKeyboardMarkup(buttons)
                await client.send_invoice(
                    chat_id=callback_query.message.chat.id,
                    title="Premium Subscription",
                    description=f"Pay {amount} Star And Get Premium For {STAR_PREMIUM_PLANS[amount]}",
                    payload=f"silentxpremium_{amount}",
                    currency="XTR",
                    prices=[LabeledPrice(label="Premium Subscription", amount=amount)],
                    reply_markup=reply_markup,
                )
                await callback_query.answer()
            except Exception as e:
                LOGGER.error(f"Error sending invoice: {e}")
                await callback_query.answer("🚫 Error Processing Your Payment. Try again.", show_alert=True)
        else:
            await callback_query.answer("⚠️ Invalid Premium Package.", show_alert=True)
    except Exception as e:
        LOGGER.error(f"Error In buy_ - {e}")


@Client.on_pre_checkout_query()
async def pre_checkout_handler(client, query: PreCheckoutQuery):
    try:
        if query.payload.startswith("silentxpremium_"):
            await query.answer(success=True)
        else:
            await query.answer(success=False, error_message="⚠️ Invalid Purchase Type.", show_alert=True)
    except Exception as e:
        LOGGER.error(f"Pre-checkout error: {e}")
        await query.answer(success=False, error_message="🚫 Unexpected Error Occurred.", show_alert=True)


@Client.on_message(filters.successful_payment)
async def successful_premium_payment(client, message):
    try:
        amount = int(message.successful_payment.total_amount)
        user_id = message.from_user.id
        time_zone = datetime.datetime.now(pytz.timezone("Asia/Kolkata"))
        current_time = time_zone.strftime("%d-%m-%Y | %I:%M:%S %p")
        if amount in STAR_PREMIUM_PLANS:
            time_str = STAR_PREMIUM_PLANS[amount]
            seconds = await get_seconds(time_str)
            if seconds > 0:
                expiry_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
                user_data = {"id": user_id, "expiry_time": expiry_time}
                await db.update_user(user_data)

                _, expiry_str_in_ist = format_expiry(expiry_time)
                await message.reply(
                    text=f"Thankyou For Purchasing Premium Service Using Star ✅\n\nSubscribtion Time - {time_str}\nExpire In - {expiry_str_in_ist}",
                    disable_web_page_preview=True,
                )
                try:
                    await client.send_message(
                        PREMIUM_LOGS,
                        text=(
                            f"#Purchase_Premium_With_Start\n\n"
                            f"👤 ᴜꜱᴇʀ - {message.from_user.mention}\n\n"
                            f"⚡ ᴜꜱᴇʀ ɪᴅ - <code>{user_id}</code>\n\n"
                            f"🚫 ꜱᴛᴀʀ ᴘᴀʏ - {amount}⭐\n\n"
                            f"⏰ ᴘʀᴇᴍɪᴜᴍ ᴀᴄᴄᴇꜱꜱ - {time_str}\n\n"
                            f"⌛️ ᴊᴏɪɴɪɴɢ ᴅᴀᴛᴇ - {current_time}\n\n"
                            f"⌛️ ᴇxᴘɪʀʏ ᴅᴀᴛᴇ - {expiry_str_in_ist}"
                        ),
                        disable_web_page_preview=True,
                    )
                except Exception:
                    pass
            else:
                await message.reply("⚠️ Invalid Premium Time.")
        else:
            await message.reply("⚠️ Invalid Premium Package.")
    except Exception as e:
        LOGGER.error(f"Error Processing Premium Payment: {e}")
        await message.reply("✅ Thank You For Your Payment! (Error Logging Details)")


@Client.on_callback_query(filters.regex("cancel_star_premium"))
async def cancel_premium(client, callback_query: CallbackQuery):
    try:
        await callback_query.message.delete()
    except Exception:
        pass
