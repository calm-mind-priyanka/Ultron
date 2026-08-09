"""
Shared MongoDB connections for the bot.

All plugins use the database handles from this module instead
of creating their own MongoDB clients.
"""

from motor.motor_asyncio import AsyncIOMotorClient

from config import Config


# ============================================================
# DATABASE CLIENT 1
# ============================================================

db1_client = AsyncIOMotorClient(
    Config.DATABASE_URI
)

db1 = db1_client[
    Config.DATABASE_NAME
]


# ============================================================
# DATABASE CLIENT 2
# ============================================================

db2_client = AsyncIOMotorClient(
    Config.DATABASE_URI_2
)

db2 = db2_client[
    Config.DATABASE_NAME
]


# ============================================================
# COMMON COLLECTIONS
# ============================================================

users_col = db1["users"]

premium_col = db1["premium_users"]

settings_col = db1["settings"]

forcesub_col = db1["forcesub_channels"]

shortlink_col = db1["shortlinks"]


# ============================================================
# FILE COLLECTIONS
# ============================================================

files_col_1 = db1["files"]

files_col_2 = db2["files"]


# ============================================================
# BACKWARD COMPATIBILITY
# ============================================================

db = db1
