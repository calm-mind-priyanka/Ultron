from motor.motor_asyncio import AsyncIOMotorClient
from info import DATABASE_URI, DATABASE_URI2
from logging_helper import LOGGER

class TopDatabase:
    def __init__(self):
        self.client1 = AsyncIOMotorClient(DATABASE_URI)
        self.db1 = self.client1["SilentXBotz"]
        self.col1 = self.db1.user

        self.has_db2 = bool(DATABASE_URI2)
        if self.has_db2:
            self.client2 = AsyncIOMotorClient(DATABASE_URI2)
            self.db2 = self.client2["SilentXBotz"]
            self.col2 = self.db2.user

    async def update_top_messages(self, user_id, message_text):
        # 1. Try DB1
        try:
            user = await self.col1.find_one({"user_id": user_id, "messages.text": message_text})
            if not user:
                await self.col1.update_one(
                    {"user_id": user_id},
                    {"$push": {"messages": {"text": message_text, "count": 1}}},
                    upsert=True
                )
            else:
                await self.col1.update_one(
                    {"user_id": user_id, "messages.text": message_text},
                    {"$inc": {"messages.$.count": 1}}
                )
            return
        except Exception as e:
            LOGGER.warning(f"DB1 top search write failed: {e}")

        # 2. Fallback to DB2 if DB1 fails
        if self.has_db2:
            try:
                user = await self.col2.find_one({"user_id": user_id, "messages.text": message_text})
                if not user:
                    await self.col2.update_one(
                        {"user_id": user_id},
                        {"$push": {"messages": {"text": message_text, "count": 1}}},
                        upsert=True
                    )
                else:
                    await self.col2.update_one(
                        {"user_id": user_id, "messages.text": message_text},
                        {"$inc": {"messages.$.count": 1}}
                    )
            except Exception:
                pass

    async def get_top_messages(self, limit=30):
        pipeline = [
            {"$unwind": "$messages"},
            {"$group": {"_id": "$messages.text", "count": {"$sum": "$messages.count"}}},
            {"$sort": {"count": -1}},
            {"$limit": limit}
        ]
        
        results = []
        try:
            res1 = await self.col1.aggregate(pipeline).to_list(length=limit)
            results.extend(res1)
        except Exception:
            pass

        if self.has_db2:
            try:
                res2 = await self.col2.aggregate(pipeline).to_list(length=limit)
                results.extend(res2)
            except Exception:
                pass

        # Sort combined results from both DBs
        combined = {}
        for item in results:
            text = item.get('_id')
            cnt = item.get('count', 0)
            if text:
                combined[text] = combined.get(text, 0) + cnt

        sorted_terms = sorted(combined.items(), key=lambda x: x[1], reverse=True)
        return [term[0] for term in sorted_terms[:limit]]

    async def delete_all_messages(self):
        try:
            await self.col1.delete_many({})
        except Exception:
            pass
            
        if self.has_db2:
            try:
                await self.col2.delete_many({})
            except Exception:
                pass

silentdb = TopDatabase()
