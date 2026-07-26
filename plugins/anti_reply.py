from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import Message


@Client.on_message(filters.group & filters.reply, group=100)
async def anti_member_reply(client: Client, message: Message):
    # Ignore anonymous messages
    if not message.from_user:
        return

    try:
        # Check if the sender is an admin
        member = await client.get_chat_member(
            message.chat.id,
            message.from_user.id
        )

        # Allow owner/admin replies
        if member.status in (
            ChatMemberStatus.OWNER,
            ChatMemberStatus.ADMINISTRATOR,
        ):
            return

        # Delete replies from normal members
        await message.delete()

    except Exception:
        pass
