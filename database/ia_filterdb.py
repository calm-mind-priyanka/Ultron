import asyncio
from struct import pack
import re
import base64
from typing import Dict, List, Tuple, Optional
from pyrogram.file_id import FileId
from pymongo.errors import DuplicateKeyError, OperationFailure, PyMongoError
from umongo import Instance, Document, fields
from motor.motor_asyncio import AsyncIOMotorClient
from marshmallow.exceptions import ValidationError
from info import *
from utils import get_settings, save_group_settings, clean_filename
from collections import defaultdict
from datetime import datetime, timedelta
from logging_helper import LOGGER
import time
from functools import lru_cache

client = AsyncIOMotorClient(DATABASE_URI, serverSelectionTimeoutMS=5000)
db = client[DATABASE_NAME]
instance = Instance.from_db(db)

client2 = AsyncIOMotorClient(DATABASE_URI2, serverSelectionTimeoutMS=5000)
db2 = client2[DATABASE_NAME]
instance2 = Instance.from_db(db2)


@instance.register
class Media(Document):
    file_id = fields.StrField(attribute='_id')
    file_ref = fields.StrField(allow_none=True)
    file_name = fields.StrField(required=True)
    file_size = fields.IntField(required=True)
    file_type = fields.StrField(allow_none=True)
    mime_type = fields.StrField(allow_none=True)
    caption = fields.StrField(allow_none=True)
    class Meta:
        indexes = ('$file_name', )
        collection_name = COLLECTION_NAME

@instance2.register
class Media2(Document):
    file_id = fields.StrField(attribute='_id')
    file_ref = fields.StrField(allow_none=True)
    file_name = fields.StrField(required=True)
    file_size = fields.IntField(required=True)
    file_type = fields.StrField(allow_none=True)
    mime_type = fields.StrField(allow_none=True)
    caption = fields.StrField(allow_none=True)
    class Meta:
        indexes = ('$file_name', )
        collection_name = COLLECTION_NAME


_db_size_cache = {
    'time': 0,
    'size': 0
}
DB_SIZE_CACHE_DURATION = 60 


@lru_cache(maxsize=256)
def get_regex_pattern(query):
    query = query.strip()
    if not query:
        raw_pattern = '.'
    else:
        cleaned_query = re.sub(r'[\s\.\+\-_]+', '', query)
        parts = [re.escape(char) for char in cleaned_query]
        raw_pattern = r"[\s\.\+\-_]*".join(parts)
        
    try:
        return re.compile(raw_pattern, flags=re.IGNORECASE)
    except Exception:
        return None


async def check_db_size(silentdb):
    try:
        global _db_size_cache
        current_time = time.time()
        is_primary = False

        if hasattr(silentdb, 'name') and silentdb.name == db.name:
            is_primary = True
        elif hasattr(silentdb, 'db') and silentdb.db.name == db.name:
            is_primary = True

        if is_primary and (current_time - _db_size_cache['time'] < DB_SIZE_CACHE_DURATION):
            return _db_size_cache['size']

        stats = None
        if hasattr(silentdb, 'command'):
            stats = await silentdb.command("dbstats")
        elif hasattr(silentdb, 'db') and hasattr(silentdb.db, 'command'):
            stats = await silentdb.db.command("dbstats")
        elif hasattr(silentdb, 'collection') and hasattr(silentdb.collection.database, 'command'):
            stats = await silentdb.collection.database.command("dbstats")

        size = stats.get('dataSize', 0) if stats else 0

        if is_primary:
            _db_size_cache['time'] = current_time
            _db_size_cache['size'] = size
        return size
    except Exception as e:
        LOGGER.error(f"Error checking DB size: {e}")
        return 0


async def save_file(media) -> Tuple[bool, int]:
    try:
        file_id, file_ref = unpack_new_file_id(media.file_id)
        file_name = clean_filename(media.file_name)
        use_secondary = False

        if MULTIPLE_DB:
            primary_db_size = await check_db_size(db)
            db_change_limit_bytes = DB_CHANGE_LIMIT * 1024 * 1024
            if primary_db_size >= db_change_limit_bytes:
                use_secondary = True

        exists = None
        try:
            exists = await Media.find_one({'_id': file_id})
        except Exception as e:
            LOGGER.warning(f"Primary DB duplicate check read error: {e}")

        if not exists and MULTIPLE_DB:
            try:
                exists = await Media2.find_one({'_id': file_id})
            except Exception as e:
                LOGGER.warning(f"Secondary DB duplicate check read error: {e}")

        if exists:
            return False, 0

        target_model = Media2 if use_secondary else Media

        file = target_model(
            file_id=file_id,
            file_ref=file_ref,
            file_name=file_name,
            file_size=media.file_size,
            file_type=media.file_type,
            mime_type=media.mime_type,
            caption=media.caption.html if media.caption else None,
        )

        try:
            await file.commit()
            return True, 1
        except (OperationFailure, PyMongoError) as db_err:
            if not use_secondary and MULTIPLE_DB:
                file2 = Media2(
                    file_id=file_id,
                    file_ref=file_ref,
                    file_name=file_name,
                    file_size=media.file_size,
                    file_type=media.file_type,
                    mime_type=media.mime_type,
                    caption=media.caption.html if media.caption else None,
                )
                await file2.commit()
                return True, 1
            else:
                raise db_err

    except ValidationError as e:
        LOGGER.error(f'Validation Error While Saving File: {e}')
        return False, 2
    except DuplicateKeyError:
        return False, 0
    except Exception as e:
        LOGGER.error(f"Unexpected error in save_file: {e}")
        return False, 3


async def get_search_results(chat_id, query, file_type=None, max_results=10, offset=0, filter=None) -> Tuple[List, int, int]:
    if chat_id is not None:
        try:
            settings = await get_settings(int(chat_id))
            user_max_btn = settings.get('max_btn')
            max_results = 10 if user_max_btn else int(MAX_B_TN)
        except Exception:
            max_results = int(MAX_B_TN)

    regex = get_regex_pattern(query)
    if not regex:
        return [], 0, 0

    if filter is None or not isinstance(filter, dict):
        if USE_CAPTION_FILTER:
            search_filter = {'$or': [{'file_name': regex}, {'name': regex}, {'caption': regex}]}
        else:
            search_filter = {'$or': [{'file_name': regex}, {'name': regex}]}
    else:
        search_filter = filter.copy()

    if file_type:
        search_filter['file_type'] = file_type

    if max_results % 2 != 0:
        max_results += 1

    projection = {'file_name': 1, 'name': 1, 'file_size': 1, 'file_id': 1, 'file_type': 1, 'caption': 1, '_id': 1}

    files = []
    count_db1 = 0
    count_db2 = 0

    try:
        count_db1 = await Media.count_documents(search_filter)
        if offset < count_db1:
            cursor1 = Media.find(search_filter, projection).sort('$natural', -1).skip(offset).limit(max_results)
            files = await cursor1.to_list(length=max_results)
    except Exception as e:
        LOGGER.error(f"Primary DB search read error: {e}")
        count_db1 = 0

    if MULTIPLE_DB:
        try:
            count_db2 = await Media2.count_documents(search_filter)
        except Exception as e:
            LOGGER.error(f"Secondary DB count read error: {e}")
            count_db2 = 0

        needed_from_db2 = max_results - len(files)
        if needed_from_db2 > 0:
            try:
                offset_db2 = max(0, offset - count_db1)
                cursor2 = Media2.find(search_filter, projection).sort('$natural', -1).skip(offset_db2).limit(needed_from_db2)
                files2 = await cursor2.to_list(length=needed_from_db2)
                files.extend(files2)
            except Exception as e:
                LOGGER.error(f"Secondary DB search read error: {e}")

    total_results = count_db1 + count_db2
    next_offset = offset + len(files)

    if next_offset >= total_results or len(files) == 0:
        next_offset = 0

    return files, next_offset, total_results


async def get_bad_files(query, file_type=None):
    regex = get_regex_pattern(query)
    if not regex:
        return [], 0

    filter_dict = {'$or': [{'file_name': regex}, {'name': regex}, {'caption': regex}]} if USE_CAPTION_FILTER else {'$or': [{'file_name': regex}, {'name': regex}]}
    if file_type:
        filter_dict['file_type'] = file_type

    files = []
    try:
        if MULTIPLE_DB:
            cursor1 = Media.find(filter_dict).sort('$natural', -1).limit(50)
            cursor2 = Media2.find(filter_dict).sort('$natural', -1).limit(50)
            res1, res2 = await asyncio.gather(cursor1.to_list(length=50), cursor2.to_list(length=50), return_exceptions=True)
            if isinstance(res1, list): files.extend(res1)
            if isinstance(res2, list): files.extend(res2)
        else:
            cursor = Media.find(filter_dict).sort('$natural', -1).limit(50)
            files = await cursor.to_list(length=50)
    except Exception as e:
        LOGGER.error(f"Error fetching bad files: {e}")

    return files, len(files)


async def get_file_details(query):
    filter_dict = {'file_id': query}
    try:
        if MULTIPLE_DB:
            res1 = await Media.find(filter_dict).to_list(length=1)
            if res1: return res1
            res2 = await Media2.find(filter_dict).to_list(length=1)
            return res2
        else:
            return await Media.find(filter_dict).to_list(length=1)
    except Exception as e:
        LOGGER.error(f"Error getting file details: {e}")
        return []


def encode_file_id(s: bytes) -> str:
    r = b""
    n = 0
    for i in s + bytes([22]) + bytes([4]):
        if i == 0:
            n += 1
        else:
            if n:
                r += b"\x00" + bytes([n])
                n = 0
            r += bytes([i])
    return base64.urlsafe_b64encode(r).decode().rstrip("=")

def encode_file_ref(file_ref: bytes) -> str:
    return base64.urlsafe_b64encode(file_ref).decode().rstrip("=")

def unpack_new_file_id(new_file_id):
    decoded = FileId.decode(new_file_id)
    file_id = encode_file_id(pack("<iiqq", int(decoded.file_type), decoded.dc_id, decoded.media_id, decoded.access_hash))
    file_ref = encode_file_ref(decoded.file_reference)
    return file_id, file_ref

_TITLE_PROJECTION = {'file_name': 1, 'name': 1, 'caption': 1, '_id': 0}

async def siletxbotz_fetch_media(limit: int) -> List[dict]:
    try:
        if MULTIPLE_DB:
            half = limit // 2
            res1 = await Media.find({}, _TITLE_PROJECTION).sort("$natural", -1).limit(half).to_list(length=half)
            res2 = await Media2.find({}, _TITLE_PROJECTION).sort("$natural", -1).limit(limit - half).to_list(length=limit - half)
            return res1 + res2
        return await Media.find({}, _TITLE_PROJECTION).sort("$natural", -1).limit(limit).to_list(length=limit)
    except Exception as e:
        LOGGER.error(f"Error in siletxbotz_fetch_media: {e}")
        return []

async def silentxbotz_clean_title(filename: str, is_series: bool = False) -> str:
    try:
        if not filename: return ""
        filename = clean_filename(filename)
        year_match = re.search(r"^(.*?)(\b\d{4}\b)", filename, re.IGNORECASE)
        if year_match: return year_match.group(1).strip().title()
        return filename.strip().title()
    except Exception:
        return filename

async def siletxbotz_get_movies(limit: int = 20) -> List[str]:
    return []

async def siletxbotz_get_series(limit: int = 30) -> Dict[str, List[int]]:
    return {}
