import asyncio
from struct import pack
import re
import base64
from typing import Dict, List, Tuple, Optional
from pyrogram.file_id import FileId
from pymongo.errors import DuplicateKeyError, OperationFailure
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

client = AsyncIOMotorClient(DATABASE_URI)
db = client[DATABASE_NAME]
instance = Instance.from_db(db)

client2 = AsyncIOMotorClient(DATABASE_URI2)
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
DB_SIZE_CACHE_DURATION = 5
_DB_WRITE_LOCK = asyncio.Lock()


@lru_cache(maxsize=512)
def get_regex_pattern(query):
    query = query.strip()
    if not query:
        raw_pattern = '.'
    elif ' ' not in query:
        raw_pattern = r"(\b|[\.\+\-_])" + re.escape(query) + r"(\b|[\.\+\-_])"
    else:
        parts = query.split(' ')
        new_parts = []
        for part in parts:
            new_parts.append(r"(\b|[\.\+\-_])" + re.escape(part) + r"(\b|[\.\+\-_])")
        raw_pattern = r".*[\s\.\+\-_()\[\]]".join(new_parts)
    try:
        return re.compile(raw_pattern, flags=re.IGNORECASE)
    except Exception:
        return None


async def check_db_size(silentdb):
    try:
        global _db_size_cache
        current_time = time.time()
        is_primary = False

        # Identify if it's the primary DB
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
    
async def get_current_db_target() -> str:
    """Return the database currently selected for NEW writes.

    This is only a write-target indicator. A full database remains fully
    readable and searchable; reaching DB_CHANGE_LIMIT only switches new
    writes from Primary to Secondary.
    """
    if not MULTIPLE_DB:
        return "Primary"

    size = await check_db_size(Media.collection.database)
    limit = int(DB_CHANGE_LIMIT) * 1024 * 1024
    return "Secondary" if size >= limit else "Primary"


async def save_file(media) -> Tuple[bool, int]:
    """
    Save a media document to the primary DB until the configured safety limit
    is reached, then use the secondary DB. If the primary DB unexpectedly
    rejects a write because its quota is exhausted, retry that file on DB2.
    """
    file_name = getattr(media, "file_name", "Unknown")
    use_secondary = False

    try:
        file_id, file_ref = unpack_new_file_id(media.file_id)
        file_name = clean_filename(media.file_name)

        # Always check both databases for duplicates. This prevents a file
        # already stored in DB2 from being inserted into DB1 again.
        exists_in_primary, exists_in_secondary = await asyncio.gather(
            Media.find_one({'_id': file_id}),
            Media2.find_one({'_id': file_id}) if MULTIPLE_DB else asyncio.sleep(0, result=None)
        )
        if exists_in_primary or exists_in_secondary:
            LOGGER.info(f'{file_name} Is Already Saved In Database!')
            return False, 0

        saveMedia = Media

        if MULTIPLE_DB:
            primary_db_size = await check_db_size(db)
            db_change_limit_bytes = int(DB_CHANGE_LIMIT * 1024 * 1024)

            if primary_db_size >= db_change_limit_bytes:
                saveMedia = Media2
                use_secondary = True

        file_kwargs = dict(
            file_id=file_id,
            file_ref=file_ref,
            file_name=file_name,
            file_size=media.file_size,
            file_type=media.file_type,
            mime_type=media.mime_type,
            caption=media.caption.html if media.caption else None,
        )

        try:
            file = saveMedia(**file_kwargs)
            await file.commit()
        except DuplicateKeyError:
            LOGGER.info(f'{file_name} Is Already Saved In {"Secondary" if use_secondary else "Primary"} Database')
            return False, 0
        except OperationFailure as e:
            # Atlas/MongoDB quota errors can happen after the size check,
            # especially while many files are being indexed concurrently.
            quota_error = any(
                text in str(e).lower()
                for text in (
                    "space quota",
                    "quota exceeded",
                    "over your space quota",
                    "storage quota",
                    "exceeded the space",
                )
            )

            if not (MULTIPLE_DB and not use_secondary and quota_error):
                raise

            # Primary became full between the check and the write.
            # Retry the same file on the secondary database.
            LOGGER.warning(
                f"Primary DB quota reached while saving {file_name}; "
                f"retrying on secondary database."
            )

            # Re-check DB2 because another concurrent task may have saved it.
            if await Media2.find_one({'_id': file_id}):
                return False, 0

            file = Media2(**file_kwargs)
            await file.commit()
            use_secondary = True

        # Keep the cached primary size moving forward after successful writes.
        # This reduces the chance that concurrent indexing tasks keep selecting
        # the primary DB using an old cached value.
        if MULTIPLE_DB and not use_secondary:
            _db_size_cache['size'] += int(getattr(media, 'file_size', 0) or 0)

        LOGGER.info(
            f'{file_name} Saved Successfully In '
            f'{"Secondary" if use_secondary else "Primary"} Database'
        )
        return True, 1

    except ValidationError as e:
        LOGGER.error(f'Validation Error While Saving File: {e}')
        return False, 2
    except DuplicateKeyError:
        LOGGER.info(f'{file_name} Is Already Saved In Database')
        return False, 0
    except Exception as e:
        LOGGER.error(f"Unexpected error in save_file: {e}")
        return False, 3


async def get_search_results(chat_id, query, file_type=None, max_results=10, offset=0, filter=None) -> Tuple[List, int, int]:
    if chat_id is not None:
        settings = await get_settings(int(chat_id))
        try:
            user_max_btn = settings.get('max_btn')
            max_results = 10 if user_max_btn else int(MAX_B_TN)
        except (KeyError, ValueError):
            await save_group_settings(int(chat_id), 'max_btn', False)
            max_results = int(MAX_B_TN)

    regex = get_regex_pattern(query)
    if not regex:
        return [], 0, 0

    if not isinstance(filter, dict):
        if USE_CAPTION_FILTER:
            filter = {'$or': [{'file_name': regex}, {'caption': regex}]}
        else:
            filter = {'file_name': regex}

    if file_type:
        filter['file_type'] = file_type

    if max_results % 2 != 0:
        max_results += 1

    projection = {
        'file_name': 1,
        'file_size': 1,
        'file_id': 1,
        'file_type': 1,
        'caption': 1,
        '_id': 1
    }

    # Search Primary first. A MongoDB quota/full condition blocks writes,
    # not reads, so a full Primary must remain searchable. If Primary is
    # temporarily unavailable, continue with Secondary instead of crashing.
    primary_files = []
    primary_count = 0
    primary_ok = False

    try:
        primary_count = await Media.count_documents(filter)
        primary_ok = True
        primary_files = await (
            Media.find(filter, projection)
            .sort('$natural', -1)
            .skip(offset)
            .limit(max_results)
            .to_list(length=max_results)
        )
    except Exception as e:
        LOGGER.warning(f"Primary DB search failed, trying Secondary: {e}")

    if not MULTIPLE_DB:
        total_results = primary_count if primary_ok else 0
        next_offset = offset + len(primary_files)
        if next_offset >= total_results or not primary_files:
            next_offset = 0
        return primary_files, next_offset, total_results

    # If Primary returned fewer results than requested, fill the remaining
    # slots from Secondary. If Primary is unavailable, start from the same
    # logical offset in Secondary.
    secondary_files = []
    secondary_count = 0
    secondary_ok = False

    try:
        secondary_count = await Media2.count_documents(filter)
        secondary_ok = True

        if len(primary_files) < max_results:
            remaining = max_results - len(primary_files)
            secondary_offset = max(0, offset - primary_count) if primary_ok else offset
            secondary_files = await (
                Media2.find(filter, projection)
                .sort('$natural', -1)
                .skip(secondary_offset)
                .limit(remaining)
                .to_list(length=remaining)
            )
    except Exception as e:
        LOGGER.warning(f"Secondary DB search failed: {e}")

    # Primary wins when the same canonical file id somehow exists in both
    # databases. This is only a safety net; save_file() already checks both
    # databases before inserting a new file.
    files = []
    seen_ids = set()

    for file in primary_files + secondary_files:
        file_id = getattr(file, 'file_id', None)
        if file_id is None:
            file_id = getattr(file, '_id', None)
        if file_id in seen_ids:
            continue
        seen_ids.add(file_id)
        files.append(file)

    # Counts are normally additive because save_file prevents duplicates.
    # If an old database contains duplicates, returned results are still
    # de-duplicated so users never see the same file twice.
    total_results = 0
    if primary_ok:
        total_results += primary_count
    if secondary_ok:
        total_results += secondary_count

    next_offset = offset + len(files)
    if next_offset >= total_results or not files:
        next_offset = 0

    return files, next_offset, total_results
    

async def get_bad_files(query, file_type=None):
    regex = get_regex_pattern(query)
    if not regex:
        return [], 0

    if USE_CAPTION_FILTER:
        filter = {'$or': [{'file_name': regex}, {'caption': regex}]}
    else:
        filter = {'file_name': regex}
    if file_type:
        filter['file_type'] = file_type

    if MULTIPLE_DB:
        # Fetch from both in parallel
        async def fetch_all(media_class):
            cursor = media_class.find(filter).sort('$natural', -1)
            count = await media_class.count_documents(filter)
            return await cursor.to_list(length=count)

        files1_task = fetch_all(Media)
        files2_task = fetch_all(Media2)
        files1, files2 = await asyncio.gather(files1_task, files2_task)
        files = files1 + files2
    else:
        cursor = Media.find(filter).sort('$natural', -1)
        count = await Media.count_documents(filter)
        files = await cursor.to_list(length=count)

    return files, len(files)
    

async def get_file_details(query):
    """Find a file in Primary first, then Secondary.

    DB quota/full state must never disable reads. A full database can still
    be queried; only writes need to move to the other database. If one DB is
    temporarily unavailable, the other DB is still attempted.
    """
    filter = {'file_id': query}

    try:
        result = await Media.find(filter).to_list(length=1)
        if result:
            return result
    except Exception as e:
        LOGGER.warning(f"Primary DB file lookup failed: {e}")

    if MULTIPLE_DB:
        try:
            result = await Media2.find(filter).to_list(length=1)
            if result:
                return result
        except Exception as e:
            LOGGER.warning(f"Secondary DB file lookup failed: {e}")

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
    file_id = encode_file_id(
        pack(
            "<iiqq",
            int(decoded.file_type),
            decoded.dc_id,
            decoded.media_id,
            decoded.access_hash
        )
    )
    file_ref = encode_file_ref(decoded.file_reference)
    return file_id, file_ref

_TITLE_PROJECTION = {'file_name': 1, 'caption': 1, '_id': 0}

async def siletxbotz_fetch_media(limit: int) -> List[dict]:
    try:
        if MULTIPLE_DB:
            half = limit // 2
            remainder = limit - half
            results = await asyncio.gather(
                Media.find({}, _TITLE_PROJECTION).sort("$natural", -1).limit(half).to_list(length=half),
                Media2.find({}, _TITLE_PROJECTION).sort("$natural", -1).limit(remainder).to_list(length=remainder)
            )
            return results[0] + results[1]

        files = await Media.find({}, _TITLE_PROJECTION).sort("$natural", -1).limit(limit).to_list(length=limit)
        return files
    except Exception as e:
        LOGGER.error(f"Error in siletxbotz_fetch_media: {e}")
        return []


async def silentxbotz_clean_title(filename: str, is_series: bool = False) -> str:
    try:
        if not filename:
            return ""
        filename = clean_filename(filename)
        year_match = re.search(r"^(.*?)(\b\d{4}\b)", filename, re.IGNORECASE)
        if year_match:
            title = year_match.group(1).strip()
            return title.title()
        if is_series:
            season_match = re.search(r"(.*?)(?:S(\d{1,2})|Season\s*(\d+))", filename, re.IGNORECASE)
            if season_match:
                title = season_match.group(1).strip()
                season_num = season_match.group(2) or season_match.group(3)
                return f"{title.title()} S{int(season_num):02}"
        return filename.strip().title()
    except Exception as e:
        LOGGER.error(f"Error in silentxbotz_clean_title: {e}")
        return filename


async def siletxbotz_get_movies(limit: int = 20) -> List[str]:
    try:
        candidates = await siletxbotz_fetch_media(limit * 2)
        results = set()
        pattern = r"(?:s\d{1,2}|season\s*\d+)(?:\s*e\d{1,2}|episode\s*\d+)?\b"
        for file in candidates:
            file_name = file.get("file_name") if isinstance(file, dict) else getattr(file, "file_name", "")
            caption = file.get("caption", "") if isinstance(file, dict) else getattr(file, "caption", "")
            if not file_name:
                continue
            if re.search(pattern, file_name, re.IGNORECASE) or (caption and re.search(pattern, caption, re.IGNORECASE)):
                continue
            title = await silentxbotz_clean_title(file_name, is_series=False)
            if title:
                results.add(title)
            if len(results) >= limit:
                break
        return sorted(list(results))[:limit]
    except Exception as e:
        LOGGER.error(f"Error in siletxbotz_get_movies: {e}")
        return []


async def siletxbotz_get_series(limit: int = 30) -> Dict[str, List[int]]:
    try:
        candidates = await siletxbotz_fetch_media(limit * 3)
        grouped = defaultdict(list)
        pattern = r"(.*?)(?:S(\d{1,2})|Season\s*(\d+))"
        for file in candidates:
            file_name = file.get("file_name") if isinstance(file, dict) else getattr(file, "file_name", "")
            caption = file.get("caption", "") if isinstance(file, dict) else getattr(file, "caption", "")
            if not file_name:
                continue
            match = re.search(pattern, file_name, re.IGNORECASE)
            if not match and caption:
                match = re.search(pattern, caption, re.IGNORECASE)
            if match:
                title_part = match.group(1)
                season_num = match.group(2) or match.group(3)
                title = await silentxbotz_clean_title(title_part, is_series=False)
                try:
                    s_num = int(season_num)
                    if s_num not in grouped[title]:
                        grouped[title].append(s_num)
                except ValueError:
                    continue
        result = {t: sorted(s) for t, s in grouped.items()}
        return dict(list(result.items())[:limit])
    except Exception as e:
        LOGGER.error(f"Error in siletxbotz_get_series: {e}")
        return {}
