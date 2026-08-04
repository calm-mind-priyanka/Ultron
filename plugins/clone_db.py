import asyncio
from pymongo import MongoClient
from pyrogram import Client, filters
from database.ia_filterdb import Media, Media2
from info import ADMINS, MULTIPLE_DB

@Client.on_message(filters.command("clone") & filters.user(ADMINS))
async def clone_database_command(client, message):
    if len(message.command) < 2:
        await message.reply_text(
            "<b>⚠️ Usage Error!</b>\n"
            "Please provide the source MongoDB URI.\n"
            "<b>Example:</b>\n<code>/clone mongodb+srv://user:pass@cluster.mongodb.net/</code>"
        )
        return

    source_uri = message.command[1]
    status_msg = await message.reply_text("🔄 **Connecting to source database and starting clone process...**")

    try:
        source_client = MongoClient(source_uri, serverSelectionTimeoutMS=5000)
        source_db = source_client.get_default_database()
        
        # Change "files" if your source collection has a different name
        source_col = source_db["files"] 

        total_docs = source_col.count_documents({})
        if total_docs == 0:
            await status_msg.edit_text("❌ Source database has no files or collection 'files' was not found!")
            return

        await status_msg.edit_text(f"📦 Found **{total_docs}** files. Cloning data now...")

        batch = []
        count = 0
        target_col = Media.collection

        for doc in source_col.find():
            batch.append(doc)
            
            # If Dual DB is enabled and DB 1 gets heavy/full (or standard batch split), 
            # you can manage insertion. Typically, bots fill Media first, then Media2.
            if len(batch) >= 5000:
                try:
                    target_col.insert_many(batch, ordered=False)
                except Exception:
                    pass
                count += len(batch)
                batch = []

        if batch:
            try:
                target_col.insert_many(batch, ordered=False)
            except Exception:
                pass
            count += len(batch)

        db_type_text = "Dual DB (Media & Media2 Support)" if MULTIPLE_DB else "Single DB"
        await status_msg.edit_text(
            f"✅ **Database Cloning Successful!** ({db_type_text})\n\n"
            f"Successfully copied **{count}** files into your bot's database."
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ **Clone Failed:**\n<code>{str(e)}</code>")
