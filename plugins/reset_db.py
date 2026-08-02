from pyrogram import Client, filters
from database.users_chats_db import db, db2
from info import ADMINS

@Client.on_message(filters.command("resetdb1") & filters.user(ADMINS))
async def reset_db1_handler(client, message):
    """Wipes ONLY the Primary Database (db1)"""
    msg = await message.reply_text("⏳ **Wiping Primary Database (db1)... Please wait.**")
    try:
        cols = await db.db.list_collection_names()
        for col in cols:
            await db.db.drop_collection(col)
        await msg.edit_text("✅ **Primary Database (db1) wiped completely!** Storage cleared to 0 MB.")
    except Exception as e:
        await msg.edit_text(f"❌ **Error clearing db1:** `{e}`")


@Client.on_message(filters.command("resetdb2") & filters.user(ADMINS))
async def reset_db2_handler(client, message):
    """Wipes ONLY the Secondary Database (db2)"""
    msg = await message.reply_text("⏳ **Wiping Secondary Database (db2)... Please wait.**")
    try:
        cols = await db2.db.list_collection_names()
        for col in cols:
            await db2.db.drop_collection(col)
        await msg.edit_text("✅ **Secondary Database (db2) wiped completely!** Storage cleared to 0 MB.")
    except Exception as e:
        await msg.edit_text(f"❌ **Error clearing db2:** `{e}`")


@Client.on_message(filters.command("resetdb_all") & filters.user(ADMINS))
async def reset_all_handler(client, message):
    """Wipes BOTH Primary and Secondary Databases"""
    msg = await message.reply_text("⏳ **Wiping BOTH Primary and Secondary Databases...**")
    try:
        for col in await db.db.list_collection_names():
            await db.db.drop_collection(col)
        for col in await db2.db.list_collection_names():
            await db2.db.drop_collection(col)
        await msg.edit_text("✅ **All databases wiped completely!** Both storage accounts are fresh.")
    except Exception as e:
        await msg.edit_text(f"❌ **Error clearing databases:** `{e}`")
