from motor.motor_asyncio import AsyncIOMotorClient
# Import DATABASE_URI2 as a fallback/write target if DB1 is full
from info import DATABASE_URI, DATABASE_URI2
from datetime import datetime

class Database:
    def __init__(self, uri, db_name):
        # Fall back to DATABASE_URI2 if URI is not provided
        target_uri = DATABASE_URI2 if DATABASE_URI2 else uri
        self.client = AsyncIOMotorClient(target_uri)
        self.db = self.client[db_name]
        self.col = self.db.user        

    async def update_top_messages(self, user_id, message_text):
        try:
            user = await self.col.find_one({"user_id": user_id, "messages.text": message_text})
            
            if not user:
                await self.col.update_one(
                    {"user_id": user_id},
                    {"$push": {"messages": {"text": message_text, "count": 1}}},
                    upsert=True
                )
            else:
                await self.col.update_one(
                    {"user_id": user_id, "messages.text": message_text},
                    {"$inc": {"messages.$.count": 1}}
                )
        except Exception:
            # If the database is full or throws a write error, 
            # ignore it so movie searching keeps working cleanly!
            pass

    async def get_top_messages(self, limit=30):
        try:
            pipeline = [
                {"$unwind": "$messages"},
                {"$group": {"_id": "$messages.text", "count": {"$sum": "$messages.count"}}},
                {"$sort": {"count": -1}},
                {"$limit": limit}
            ]
            results = await self.col.aggregate(pipeline).to_list(length=limit)
            return [result['_id'] for result in results]
        except Exception:
            return []
    
    async def delete_all_messages(self):
        try:
            await self.col.delete_many({})
        except Exception:
            pass

# Connect topdb directly to DATABASE_URI2 if available, or fallback to DATABASE_URI
db_target = DATABASE_URI2 if DATABASE_URI2 else DATABASE_URI
silentdb = Database(db_target, "SilentXBotz")
