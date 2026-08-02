import motor.motor_asyncio
from info import *  
from datetime import timedelta, timezone
import time, datetime, pytz
from pymongo.errors import DuplicateKeyError
from pymongo import MongoClient
from logging_helper import LOGGER

class Database:    
    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.col = self.db.users
        self.grp = self.db.groups
        self.users = self.db.uersz  # Ensure admin commands also use db.users!
        self.botcol = self.db.bot_settings
        self.misc = self.db.misc
        self.verify_id = self.db.verify_id 
        self.codes = self.db.codes
        self.connection = self.db.connections

    async def find_join_req(self, id, chnl):
        chnl = str(chnl)
        res = await self.db.request[chnl].find_one({'id': int(id)})
        if not res and 'db2' in globals():
            res = await db2.db.request[chnl].find_one({'id': int(id)})
        return bool(res)
     
    async def add_join_req(self, id, chnl):
        chnl = str(chnl)
        try:
            await self.db.request[chnl].insert_one({'id': int(id)})
        except Exception:
            if 'db2' in globals():
                try:
                    await db2.db.request[chnl].insert_one({'id': int(id)})
                except Exception:
                    pass

    async def del_join_req(self):
        if AUTH_REQ_CHANNEL:
            for c in AUTH_REQ_CHANNEL:
                try:
                    c = str(c)
                    await self.db.request[c].delete_many({})
                    if 'db2' in globals():
                        await db2.db.request[c].delete_many({})
                except Exception:
                    pass

    def new_user(self, id, name):
        return dict(
            id = int(id),
            name = name,
            ban_status=dict(
                is_banned=False,
                ban_reason="",
            ),
        )

    def new_group(self, id, title):
        return dict(
            id = int(id),
            title = title,
            chat_status=dict(
                is_disabled=False,
                reason="",
            ),
        )
    
    async def add_user(self, id, name):
        user = self.new_user(id, name)
        try:
            await self.col.insert_one(user)
        except Exception:
            if 'db2' in globals():
                try:
                    await db2.col.insert_one(user)
                except Exception:
                    pass
    
    async def is_user_exist(self, id):
        user = await self.col.find_one({'id': int(id)})
        if not user and 'db2' in globals():
            user = await db2.col.find_one({'id': int(id)})
        return bool(user)
    
    async def total_users_count(self):
        count = await self.col.count_documents({})
        if 'db2' in globals():
            count += await db2.col.count_documents({})
        return count
    
    async def remove_ban(self, id):
        try:
            ban_status = dict(is_banned=False, ban_reason='')
            await self.col.update_one({'id': int(id)}, {'$set': {'ban_status': ban_status}})
        except Exception:
            pass
        if 'db2' in globals():
            try:
                ban_status = dict(is_banned=False, ban_reason='')
                await db2.col.update_one({'id': int(id)}, {'$set': {'ban_status': ban_status}})
            except Exception:
                pass
    
    async def ban_user(self, user_id, ban_reason="No Reason"):
        ban_status = dict(is_banned=True, ban_reason=ban_reason)
        try:
            await self.col.update_one({'id': int(user_id)}, {'$set': {'ban_status': ban_status}})
        except Exception:
            pass
        if 'db2' in globals():
            try:
                await db2.col.update_one({'id': int(user_id)}, {'$set': {'ban_status': ban_status}})
            except Exception:
                pass

    async def get_ban_status(self, id):
        default = dict(is_banned=False, ban_reason='')
        user = await self.col.find_one({'id': int(id)})
        if not user and 'db2' in globals():
            user = await db2.col.find_one({'id': int(id)})
        if not user:
            return default
        return user.get('ban_status', default)

    async def get_all_users(self):
        return self.col.find({})
    
    async def delete_user(self, user_id):
        try:
            await self.col.delete_many({'id': int(user_id)})
        except Exception:
            pass
        if 'db2' in globals():
            try:
                await db2.col.delete_many({'id': int(user_id)})
            except Exception:
                pass
        
    async def delete_chat(self, id):
        try:
            await self.grp.delete_many({'id': int(id)})    
        except Exception:
            pass
        if 'db2' in globals():
            try:
                await db2.grp.delete_many({'id': int(id)})
            except Exception:
                pass

    async def get_banned(self):
        users = self.col.find({'ban_status.is_banned': True})
        chats = self.grp.find({'chat_status.is_disabled': True})
        b_chats = [chat['id'] async for chat in chats]
        b_users = [user['id'] async for user in users]
        return b_users, b_chats
    
    async def add_chat(self, chat, title):
        chat_data = self.new_group(chat, title)
        try:
            await self.grp.update_one({'id': int(chat)}, {'$set': chat_data}, upsert=True)
        except Exception:
            if 'db2' in globals():
                try:
                    await db2.grp.update_one({'id': int(chat)}, {'$set': chat_data}, upsert=True)
                except Exception:
                    pass
    
    async def get_chat(self, chat):
        chat_doc = await self.grp.find_one({'id': int(chat)})
        if not chat_doc and 'db2' in globals():
            chat_doc = await db2.grp.find_one({'id': int(chat)})
        return False if not chat_doc else chat_doc.get('chat_status')
    
    async def re_enable_chat(self, id):
        chat_status=dict(is_disabled=False, reason="")
        try:
            await self.grp.update_one({'id': int(id)}, {'$set': {'chat_status': chat_status}})
        except Exception:
            pass
        if 'db2' in globals():
            try:
                await db2.grp.update_one({'id': int(id)}, {'$set': {'chat_status': chat_status}})
            except Exception:
                pass
        
    async def update_settings(self, id, settings):
        try:
            await self.grp.update_one({'id': int(id)}, {'$set': {'settings': settings}}, upsert=True)
        except Exception:
            if 'db2' in globals():
                try:
                    await db2.grp.update_one({'id': int(id)}, {'$set': {'settings': settings}}, upsert=True)
                except Exception:
                    pass
            
    async def get_settings(self, id):
        default = {
            'button': BUTTON_MODE,
            'botpm': P_TTI_SHOW_OFF,
            'file_secure': PROTECT_CONTENT,
            'imdb': IMDB,
            'spell_check': SPELL_CHECK_REPLY,
            'welcome': MELCOW_NEW_USERS,
            'auto_delete': AUTO_DELETE,
            'auto_del_time': AUTO_DELETE_TIME,
            'auto_ffilter': AUTO_FFILTER,
            'max_btn': MAX_BTN,
            'template': IMDB_TEMPLATE,
            'log': LOG_VR_CHANNEL,
            'tutorial': TUTORIAL,
            'tutorial_2': TUTORIAL_2,
            'tutorial_3': TUTORIAL_3,
            'shortner': SHORTENER_WEBSITE,
            'api': SHORTENER_API,
            'shortner_two': SHORTENER_WEBSITE2,
            'api_two': SHORTENER_API2,
            'shortner_three': SHORTENER_WEBSITE3,
            'api_three': SHORTENER_API3,
            'is_verify': IS_VERIFY,
            'verify_time': TWO_VERIFY_GAP,
            'third_verify_time': THREE_VERIFY_GAP,
            'caption': CUSTOM_FILE_CAPTION,
            'fsub_id': AUTH_CHANNEL
        }
        chat = await self.grp.find_one({'id': int(id)})
        if not chat and 'db2' in globals():
            chat = await db2.grp.find_one({'id': int(id)})
            
        if chat and 'settings' in chat:
            return {**default, **chat['settings']}
        else:
            return default.copy()

    async def delete_setting(self, id, key):
        try:
            await self.grp.update_one({'id': int(id)}, {'$unset': {f'settings.{key}': ""}})
        except Exception:
            pass
        if 'db2' in globals():
            try:
                await db2.grp.update_one({'id': int(id)}, {'$unset': {f'settings.{key}': ""}})
            except Exception:
                pass

    async def silentx_reset_settings(self):
        try:
            result = await self.grp.update_many({'settings': {'$exists': True}}, {'$unset': {'settings': ''}})
            return result.modified_count
        except Exception as e:
            LOGGER.error(f"Error deleting settings for all groups: {str(e)}")
            raise
            
    async def disable_chat(self, chat, reason="No Reason"):
        chat_status=dict(is_disabled=True, reason=reason)
        try:
            await self.grp.update_one({'id': int(chat)}, {'$set': {'chat_status': chat_status}})
        except Exception:
            pass
        if 'db2' in globals():
            try:
                await db2.grp.update_one({'id': int(chat)}, {'$set': {'chat_status': chat_status}})
            except Exception:
                pass

    async def total_chat_count(self):
        count = await self.grp.count_documents({})
        if 'db2' in globals():
            count += await db2.grp.count_documents({})
        return count
    
    async def get_all_chats(self):
        return self.grp.find({})

    async def get_db_size(self):
        return (await self.db.command("dbstats"))['dataSize']

    async def get_user(self, user_id):
        user_id = int(user_id)
        # Try DB1 first
        try:
            user_data = await self.users.find_one({"id": user_id})
            if user_data:
                return user_data
        except Exception:
            pass
            
        # Check DB2 if DB1 yielded nothing or failed
        if 'db2' in globals():
            try:
                return await db2.users.find_one({"id": user_id})
            except Exception:
                pass
        return None
        
    async def update_user(self, user_data):
        user_data["id"] = int(user_data["id"])
        # Try DB1
        try:
            await self.users.update_one({"id": user_data["id"]}, {"$set": user_data}, upsert=True)
            return True
        except Exception:
            pass
            
        # Fallback write to DB2 if DB1 is full/failed
        if 'db2' in globals():
            try:
                await db2.users.update_one({"id": user_data["id"]}, {"$set": user_data}, upsert=True)
                return True
            except Exception:
                pass
        return False

    async def get_notcopy_user(self, user_id):
        user_id = int(user_id)
        user = await self.misc.find_one({"user_id": user_id})
        if not user and 'db2' in globals():
            user = await db2.misc.find_one({"user_id": user_id})

        ist_timezone = pytz.timezone('Asia/Kolkata')
        if not user:
            res = {
                "user_id": user_id,
                "last_verified": datetime.datetime(2020, 5, 17, 0, 0, 0, tzinfo=ist_timezone),
                "second_time_verified": datetime.datetime(2019, 5, 17, 0, 0, 0, tzinfo=ist_timezone),
            }
            try:
                await self.misc.insert_one(res)
            except Exception:
                if 'db2' in globals():
                    try:
                        await db2.misc.insert_one(res)
                    except Exception:
                        pass
            return res
        return user

    async def update_notcopy_user(self, user_id, value:dict):
        user_id = int(user_id)
        myquery = {"user_id": user_id}
        newvalues = {"$set": value}
        try:
            return await self.misc.update_one(myquery, newvalues)
        except Exception:
            if 'db2' in globals():
                try:
                    return await db2.misc.update_one(myquery, newvalues)
                except Exception:
                    pass

    async def is_user_verified(self, user_id):
        user = await self.get_notcopy_user(user_id)
        try:
            pastDate = user["last_verified"]
        except Exception:
            user = await self.get_notcopy_user(user_id)
            pastDate = user["last_verified"]
        ist_timezone = pytz.timezone('Asia/Kolkata')
        
        if pastDate.tzinfo is None:
            pastDate = pytz.utc.localize(pastDate)
            
        pastDate = pastDate.astimezone(ist_timezone)
        current_time = datetime.datetime.now(tz=ist_timezone)
        seconds_since_midnight = (current_time - datetime.datetime(current_time.year, current_time.month, current_time.day, 0, 0, 0, tzinfo=ist_timezone)).total_seconds()
        time_diff = current_time - pastDate
        total_seconds = time_diff.total_seconds()
        return total_seconds <= seconds_since_midnight

    async def user_verified(self, user_id):
        user = await self.get_notcopy_user(user_id)
        try:
            pastDate = user["second_time_verified"]
        except Exception:
            user = await self.get_notcopy_user(user_id)
            pastDate = user["second_time_verified"]
        ist_timezone = pytz.timezone('Asia/Kolkata')
        
        if pastDate.tzinfo is None:
            pastDate = pytz.utc.localize(pastDate)
            
        pastDate = pastDate.astimezone(ist_timezone)
        current_time = datetime.datetime.now(tz=ist_timezone)
        seconds_since_midnight = (current_time - datetime.datetime(current_time.year, current_time.month, current_time.day, 0, 0, 0, tzinfo=ist_timezone)).total_seconds()
        time_diff = current_time - pastDate
        total_seconds = time_diff.total_seconds()
        return total_seconds <= seconds_since_midnight

    async def use_second_shortener(self, user_id, time):
        user = await self.get_notcopy_user(user_id)
        if not user.get("second_time_verified"):
            ist_timezone = pytz.timezone('Asia/Kolkata')
            await self.update_notcopy_user(user_id, {"second_time_verified":datetime.datetime(2019, 5, 17, 0, 0, 0, tzinfo=ist_timezone)})
            user = await self.get_notcopy_user(user_id)
        if await self.is_user_verified(user_id):
            try:
                pastDate = user["last_verified"]
            except Exception:
                user = await self.get_notcopy_user(user_id)
                pastDate = user["last_verified"]
            ist_timezone = pytz.timezone('Asia/Kolkata')
            
            if pastDate.tzinfo is None:
                pastDate = pytz.utc.localize(pastDate)
                
            pastDate = pastDate.astimezone(ist_timezone)
            current_time = datetime.datetime.now(tz=ist_timezone)
            time_difference = current_time - pastDate
            if time_difference > datetime.timedelta(seconds=time):
                second_time = user["second_time_verified"]
                if second_time.tzinfo is None:
                    second_time = pytz.utc.localize(second_time)
                second_time = second_time.astimezone(ist_timezone)
                return second_time < pastDate
        return False

    async def use_third_shortener(self, user_id, time):
        user = await self.get_notcopy_user(user_id)
        if not user.get("third_time_verified"):
            ist_timezone = pytz.timezone('Asia/Kolkata')
            await self.update_notcopy_user(user_id, {"third_time_verified":datetime.datetime(2018, 5, 17, 0, 0, 0, tzinfo=ist_timezone)})
            user = await self.get_notcopy_user(user_id)
        if await self.user_verified(user_id):
            try:
                pastDate = user["second_time_verified"]
            except Exception:
                user = await self.get_notcopy_user(user_id)
                pastDate = user["second_time_verified"]
            ist_timezone = pytz.timezone('Asia/Kolkata')
            
            if pastDate.tzinfo is None:
                pastDate = pytz.utc.localize(pastDate)
                
            pastDate = pastDate.astimezone(ist_timezone)
            current_time = datetime.datetime.now(tz=ist_timezone)
            time_difference = current_time - pastDate
            if time_difference > datetime.timedelta(seconds=time):
                second_time = user["third_time_verified"]
                if second_time.tzinfo is None:
                    second_time = pytz.utc.localize(second_time)
                second_time = second_time.astimezone(ist_timezone)
                return second_time < pastDate
        return False
   
    async def create_verify_id(self, user_id: int, hash):
        res = {"user_id": int(user_id), "hash": hash, "verified": False}
        try:
            return await self.verify_id.insert_one(res)
        except Exception:
            if 'db2' in globals():
                try:
                    return await db2.verify_id.insert_one(res)
                except Exception:
                    pass

    async def get_verify_id_info(self, user_id: int, hash):
        res = await self.verify_id.find_one({"user_id": int(user_id), "hash": hash})
        if not res and 'db2' in globals():
            res = await db2.verify_id.find_one({"user_id": int(user_id), "hash": hash})
        return res

    async def update_verify_id_info(self, user_id, hash, value: dict):
        myquery = {"user_id": int(user_id), "hash": hash}
        newvalues = { "$set": value }
        try:
            return await self.verify_id.update_one(myquery, newvalues)
        except Exception:
            if 'db2' in globals():
                try:
                    return await db2.verify_id.update_one(myquery, newvalues)
                except Exception:
                    pass
        
    async def has_premium_access(self, user_id):
        user_id = int(user_id)
        user_data = await self.get_user(user_id)
        if user_data:
            expiry_time = user_data.get("expiry_time")
            if expiry_time is None:
                return False
            elif isinstance(expiry_time, datetime.datetime):
                if expiry_time.tzinfo is None:
                    expiry_time = pytz.utc.localize(expiry_time)
                
                now = datetime.datetime.now(timezone.utc)
                if now <= expiry_time:
                    return True
                else:
                    try:
                        await self.users.update_one({"id": user_id}, {"$set": {"expiry_time": None}})
                    except Exception:
                        if 'db2' in globals():
                            try:
                                await db2.users.update_one({"id": user_id}, {"$set": {"expiry_time": None}})
                            except Exception:
                                pass
        return False

    async def update_one(self, filter_query, update_data):
        try:
            return await self.users.update_one(filter_query, update_data)
        except Exception as e:
            if 'db2' in globals():
                try:
                    return await db2.users.update_one(filter_query, update_data)
                except Exception:
                    pass
            LOGGER.error(f"Error updating document: {e}")
            return False
            
    async def get_expired(self, current_time):
        expired_users = []
        cursor = self.users.find({"expiry_time": {"$lt": current_time}})
        async for user in cursor:
            expired_users.append(user)
        if 'db2' in globals():
            cursor2 = db2.users.find({"expiry_time": {"$lt": current_time}})
            async for user in cursor2:
                expired_users.append(user)
        return expired_users

    async def get_expiring_soon(self, label, delta):
        reminder_key = f"reminder_{label}_sent"
        now = datetime.datetime.now(timezone.utc)
        target_time = now + delta
        window = timedelta(seconds=30)

        start_range = target_time - window
        end_range = target_time + window

        reminder_users = []
        cursor = self.users.find({
            "expiry_time": {"$gte": start_range, "$lte": end_range},
            reminder_key: {"$ne": True}
        })

        async for user in cursor:
            reminder_users.append(user)
            try:
                await self.users.update_one(
                    {"id": int(user["id"])}, {"$set": {reminder_key: True}}
                )
            except Exception:
                if 'db2' in globals():
                    try:
                        await db2.users.update_one(
                            {"id": int(user["id"])}, {"$set": {reminder_key: True}}
                        )
                    except Exception:
                        pass

        return reminder_users

    async def remove_premium_access(self, user_id):
        user_id = int(user_id)
        return await self.update_one(
            {"id": user_id}, {"$set": {"expiry_time": None}}
        )

    async def check_trial_status(self, user_id):
        user_id = int(user_id)
        user_data = await self.get_user(user_id)
        if user_data:
            return user_data.get("has_free_trial", False)
        return False

    async def give_free_trial(self, user_id):
        user_id = int(user_id)
        seconds = 5 * 60         
        expiry_time = datetime.datetime.now(timezone.utc) + datetime.timedelta(seconds=seconds)
        user_data = {"id": user_id, "expiry_time": expiry_time, "has_free_trial": True}
        try:
            await self.users.update_one({"id": user_id}, {"$set": user_data}, upsert=True)
        except Exception:
            if 'db2' in globals():
                try:
                    await db2.users.update_one({"id": user_id}, {"$set": user_data}, upsert=True)
                except Exception:
                    pass

    async def all_premium_users(self):
        now = datetime.datetime.now(timezone.utc)
        count = await self.users.count_documents({"expiry_time": {"$gt": now}})
        if 'db2' in globals():
            count += await db2.users.count_documents({"expiry_time": {"$gt": now}})
        return count
    
    async def get_bot_setting(self, bot_id, setting_key, default_value):
        bot = await self.botcol.find_one({'id': int(bot_id)}, {setting_key: 1, '_id': 0})
        if not bot and 'db2' in globals():
            bot = await db2.botcol.find_one({'id': int(bot_id)}, {setting_key: 1, '_id': 0})
        return bot[setting_key] if bot and setting_key in bot else default_value
        
    async def update_bot_setting(self, bot_id, setting_key, value):
        try:
            await self.botcol.update_one({'id': int(bot_id)}, {'$set': {setting_key: value}}, upsert=True)
        except Exception:
            if 'db2' in globals():
                try:
                    await db2.botcol.update_one({'id': int(bot_id)}, {'$set': {setting_key: value}}, upsert=True)
                except Exception:
                    pass

    async def connect_group(self, group_id, user_id):
        group_id = int(group_id)
        user_id = int(user_id)
        try:
            user = await self.connection.find_one({'_id': user_id})
            if user:
                if group_id not in user["group_ids"]:
                    await self.connection.update_one({'_id': user_id}, {"$push": {"group_ids": group_id}})
            else:
                await self.connection.insert_one({'_id': user_id, 'group_ids': [group_id]})
        except Exception:
            if 'db2' in globals():
                try:
                    user2 = await db2.connection.find_one({'_id': user_id})
                    if user2:
                        if group_id not in user2["group_ids"]:
                            await db2.connection.update_one({'_id': user_id}, {"$push": {"group_ids": group_id}})
                    else:
                        await db2.connection.insert_one({'_id': user_id, 'group_ids': [group_id]})
                except Exception:
                    pass

    async def get_connected_grps(self, user_id):
        user = await self.connection.find_one({'_id': int(user_id)})
        if not user and 'db2' in globals():
            user = await db2.connection.find_one({'_id': int(user_id)})
        if user:
            return user["group_ids"]
        else:
            return []

    async def get_maintenance_status(self, bot_id):
        return await self.get_bot_setting(bot_id, 'MAINTENANCE_MODE', MAINTENANCE_MODE)

    async def update_maintenance_status(self, bot_id, enable):
        await self.update_bot_setting(bot_id, 'MAINTENANCE_MODE', enable)

    async def pm_search_status(self, bot_id):
        return await self.get_bot_setting(bot_id, 'PM_SEARCH', PM_SEARCH)

    async def update_pm_search_status(self, bot_id, enable):
        await self.update_bot_setting(bot_id, 'PM_SEARCH', enable)

    async def movie_update_status(self, bot_id):
        return await self.get_bot_setting(bot_id, 'MOVIE_UPDATE_NOTIFICATION', MOVIE_UPDATE_NOTIFICATION)

    async def update_movie_update_status(self, bot_id, enable):
        await self.update_bot_setting(bot_id, 'MOVIE_UPDATE_NOTIFICATION', enable)

db = Database(DATABASE_URI, DATABASE_NAME)    
db2 = Database(DATABASE_URI2, DATABASE_NAME)
