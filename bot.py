import os
import re
from telethon import TelegramClient
import sqlite3
import asyncio

from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from telegram import (
    Update,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.constants import ChatMemberStatus

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    ChatMemberHandler,
    filters,
)


# ==============================
# 🔰 BOT BASIC SETUP
# ==============================

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not API_ID or not API_HASH:
    raise RuntimeError("API_ID / API_HASH မထည့်ရသေးပါ")

resolver = TelegramClient(
    "username_resolver",
    int(API_ID),
    API_HASH
)


if not TOKEN:
    raise RuntimeError(
        "❌ BOT_TOKEN မတွေ့ပါ။ .env ဖိုင်ကို စစ်ပါ။"
    )


DB_FILE = "bot.db"

MAX_WARNINGS = 3

AUTO_MUTE_SECONDS = 30


# ==============================
# 🔗 LINK DETECTOR
# ==============================

LINK_REGEX = re.compile(
    r"(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)",
    re.IGNORECASE
)


USERNAME_REGEX = re.compile(
    r"@[A-Za-z0-9_]{5,32}"
)
# ==============================
# 🗄️ DATABASE
# ==============================

db = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)

db.row_factory = sqlite3.Row


# ==============================
# ⚙️ SETTINGS TABLE
# ==============================

db.execute("""
CREATE TABLE IF NOT EXISTS settings (
    chat_id INTEGER PRIMARY KEY,

    link_filter INTEGER DEFAULT 1,

    forward_filter INTEGER DEFAULT 1,

    bio_filter INTEGER DEFAULT 1,

    join_delete INTEGER DEFAULT 1,

    leave_delete INTEGER DEFAULT 1,

    vc_start_delete INTEGER DEFAULT 1,

    vc_end_delete INTEGER DEFAULT 1
)
""")


# ==============================
# ⚠️ WARNINGS TABLE
# ==============================

db.execute("""
CREATE TABLE IF NOT EXISTS warnings (
    chat_id INTEGER NOT NULL,

    user_id INTEGER NOT NULL,

    count INTEGER DEFAULT 0,

    PRIMARY KEY (chat_id, user_id)
)
""")


db.commit()

# ==============================
# 👤 USER CACHE TABLE
# ==============================

db.execute("""
CREATE TABLE IF NOT EXISTS user_cache (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT,
    full_name TEXT,
    PRIMARY KEY (chat_id, user_id)
)
""")

db.commit()


# ==============================
# 👤 USER CACHE FUNCTION
# ==============================

def cache_user(chat_id, user):
    if not user:
        return

    username = (
        user.username.lower()
        if user.username
        else None
    )

    db.execute(
        """
        INSERT INTO user_cache
        (chat_id, user_id, username, full_name)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id, user_id)
        DO UPDATE SET
            username = excluded.username,
            full_name = excluded.full_name
        """,
        (
            chat_id,
            user.id,
            username,
            user.full_name
        )
    )

    db.commit()



# ==============================
# 💬 AUTO REPLY TABLE
# ==============================

db.execute("""
CREATE TABLE IF NOT EXISTS auto_replies (
    chat_id INTEGER NOT NULL,
    trigger TEXT NOT NULL,
    reply_type TEXT NOT NULL,
    reply_text TEXT,
    file_id TEXT,
    PRIMARY KEY (chat_id, trigger)
)
""")

db.commit()

# ==============================
# 💬 AUTO REPLY FUNCTIONS
# ==============================

def normalize_trigger(text):
    return text.strip().lower()


def get_auto_reply(chat_id, trigger):
    return db.execute(
        """
        SELECT *
        FROM auto_replies
        WHERE chat_id = ?
        AND trigger = ?
        """,
        (chat_id, normalize_trigger(trigger))
    ).fetchone()


def save_auto_reply(
    chat_id,
    trigger,
    reply_type,
    reply_text=None,
    file_id=None
):
    trigger = normalize_trigger(trigger)

    db.execute(
        """
        INSERT INTO auto_replies
        (
            chat_id,
            trigger,
            reply_type,
            reply_text,
            file_id
        )
        VALUES (?, ?, ?, ?, ?)

        ON CONFLICT(chat_id, trigger)
        DO UPDATE SET
            reply_type = excluded.reply_type,
            reply_text = excluded.reply_text,
            file_id = excluded.file_id
        """,
        (
            chat_id,
            trigger,
            reply_type,
            reply_text,
            file_id
        )
    )

    db.commit()


# ==============================
# ➕ ADD REPLY
# ==============================

async def addreply_command(update, context):
    if not await is_admin(update, update.effective_user.id):
        return

    message = update.effective_message

    if not message.reply_to_message:
        await message.reply_text(
            "❌ Reply လုပ်ပြီး /addreply hi လို့ရေးပါ။"
        )
        return

    if not context.args:
        await message.reply_text(
            "❌ Trigger ထည့်ပါ။ ဥပမာ - /addreply hi"
        )
        return

    trigger = normalize_trigger(" ".join(context.args))
    replied = message.reply_to_message

    reply_type = None
    reply_text = None
    file_id = None

    if replied.text:
        reply_type = "text"
        reply_text = replied.text

    elif replied.sticker:
        reply_type = "sticker"
        file_id = replied.sticker.file_id

    elif replied.photo:
        reply_type = "photo"
        file_id = replied.photo[-1].file_id
        reply_text = replied.caption

    elif replied.video:
        reply_type = "video"
        file_id = replied.video.file_id
        reply_text = replied.caption

    elif replied.document:
        if replied.document.mime_type == "application/vnd.android.package-archive":
            reply_type = "apk"
        else:
            reply_type = "document"

        file_id = replied.document.file_id
        reply_text = replied.caption

    elif replied.audio:
        reply_type = "audio"
        file_id = replied.audio.file_id
        reply_text = replied.caption

    elif replied.voice:
        reply_type = "voice"
        file_id = replied.voice.file_id
        reply_text = replied.caption

    elif replied.animation:
        reply_type = "animation"
        file_id = replied.animation.file_id
        reply_text = replied.caption

    else:
        await message.reply_text(
            "❌ ဒီ message type ကို Auto Reply အဖြစ် မသိမ်းနိုင်သေးပါ။"
        )
        return

    save_auto_reply(
        update.effective_chat.id,
        trigger,
        reply_type,
        reply_text,
        file_id
    )

    labels = {
        "text": "💬 Text",
        "sticker": "🎨 Sticker",
        "photo": "🖼️ Photo",
        "video": "🎬 Video",
        "document": "📦 File",
        "apk": "📱 APK",
        "audio": "🎵 Audio",
        "voice": "🎤 Voice",
        "animation": "🎞️ GIF"
    }

    await message.reply_text(
        f"✅ Auto Reply သိမ်းပြီးပါပြီ။\n"
        f"🔑 Trigger: {trigger}\n"
        f"📦 Type: {labels.get(reply_type, reply_type)}"
    )


# ==============================
# 📋 REPLY LIST
# ==============================

async def replies_command(update, context):
    if not await is_admin(update, update.effective_user.id):
        return

    rows = db.execute(
        """
        SELECT trigger, reply_type
        FROM auto_replies
        WHERE chat_id = ?
        ORDER BY trigger COLLATE NOCASE
        """,
        (update.effective_chat.id,)
    ).fetchall()

    if not rows:
        await update.effective_message.reply_text(
        """⚙️ BOT SETTINGS

🔧 အောက်က Button များမှတစ်ဆင့်
🟢 Feature များကို ON / OFF စီမံနိုင်ပါတယ်။""",
        reply_markup=settings_keyboard(chat_id)
    )
# ==============================
# 🔘 SETTINGS BUTTON
# ==============================

async def settings_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    chat_id = query.message.chat.id

    if not await is_admin(
        update,
        query.from_user.id
    ):
        await query.answer(
            "❌ Admin only!",
            show_alert=True
        )
        return

    settings = get_settings(chat_id)

    setting_map = {
        "set_link": "link_filter",
        "set_forward": "forward_filter",
        "set_bio": "bio_filter",
        "set_join": "join_delete",
        "set_leave": "leave_delete",
        "set_vcstart": "vc_start_delete",
        "set_vcend": "vc_end_delete",
    }

    data = query.data

    if data in setting_map:

        column = setting_map[data]

        current = settings[column]

        set_setting(
            chat_id,
            column,
            not bool(current)
        )

        settings = get_settings(chat_id)

        await query.edit_message_reply_markup(
            reply_markup=settings_keyboard(chat_id)
        )

        return

    if data == "settings_refresh":

        await query.edit_message_reply_markup(
            reply_markup=settings_keyboard(chat_id)
        )

        return
# ==============================
# 👤 GET TARGET USER
# ==============================

async def get_user_bio(context, user_id):
    return None


async def get_target_user(update, context):
    message = update.effective_message
    chat_id = update.effective_chat.id

    if not message:
        return None

    # ==========================================
    # 1️⃣ REPLY -> /info
    # ==========================================
    if message.reply_to_message:
        u = message.reply_to_message.from_user

        if u:
            try:
                cache_user(chat_id, u)
            except Exception:
                pass

            return u

    # ==========================================
    # 2️⃣ ARGUMENT
    # ==========================================
    if not context.args:
        return None

    value = " ".join(context.args).strip()

    if not value:
        return None

    search = value.casefold().strip()

    # ==========================================
    # 3️⃣ NAME SEARCH FIRST
    # IMPORTANT:
    # "09448012932" can be a DISPLAY NAME,
    # not necessarily a Telegram User ID.
    # ==========================================

    # ---- Local cache ----
    try:
        rows = db.execute(
            """
            SELECT user_id, username, full_name
            FROM user_cache
            WHERE chat_id = ?
            AND full_name IS NOT NULL
            """,
            (chat_id,)
        ).fetchall()

        for row in rows:
            full_name = (row["full_name"] or "").strip()
            fn = full_name.casefold()

            if (
                fn == search
                or fn.startswith(search + " ")
                or search in fn
            ):
                uid = int(row["user_id"])

                # Try Telethon cache/entity
                try:
                    entity = await resolver.get_entity(uid)
                    return entity
                except Exception:
                    pass

                # Try Bot API
                try:
                    member = await context.bot.get_chat_member(
                        chat_id=chat_id,
                        user_id=uid
                    )
                    return member.user
                except Exception:
                    pass

    except Exception as e:
        print("CACHE NAME SEARCH ERROR:", repr(e))

    # ==========================================
    # Telethon group member search
    # ==========================================
    try:
        participants = await resolver.get_participants(
            chat_id,
            limit=None
        )

        for user in participants:

            first = (
                getattr(user, "first_name", None)
                or ""
            ).strip()

            last = (
                getattr(user, "last_name", None)
                or ""
            ).strip()

            username = (
                getattr(user, "username", None)
                or ""
            ).strip()

            full_name = " ".join(
                x for x in [first, last] if x
            ).strip()

            full_cf = full_name.casefold()
            first_cf = first.casefold()
            last_cf = last.casefold()
            username_cf = username.casefold()

            # Exact name / first name / last name / partial name
            if (
                full_cf == search
                or first_cf == search
                or last_cf == search
                or search in full_cf
                or (
                    username
                    and username_cf == search.lstrip("@")
                )
            ):

                try:
                    cache_user(chat_id, user)
                except Exception:
                    pass

                return user

    except Exception as e:
        print("TELETHON PARTICIPANT SEARCH ERROR:", repr(e))

    # ==========================================
    # 4️⃣ USERNAME SEARCH
    # ==========================================
    username = value.lstrip("@").strip()

    if username:
        try:
            entity = await resolver.get_entity(username)

            try:
                cache_user(chat_id, entity)
            except Exception:
                pass

            return entity

        except Exception as e:
            print("TELETHON USERNAME ERROR:", repr(e))

    # ==========================================
    # 5️⃣ USER ID
    # ONLY AFTER NAME SEARCH
    # ==========================================
    if value.isdigit():

        uid = int(value)

        try:
            entity = await resolver.get_entity(uid)
            return entity

        except Exception as e:
            print("TELETHON ID ERROR:", repr(e))

        try:
            member = await context.bot.get_chat_member(
                chat_id=chat_id,
                user_id=uid
            )
            return member.user

        except Exception as e:
            print("BOT ID ERROR:", repr(e))

    return None

async def info_command(
    update,
    context
):
    target = await resolve_target(update, context)

    if not target:
        await update.effective_message.reply_text(
            '❌ USER NOT FOUND\n\n📌 /info @username\n📌 /info USER_ID\n📌 Reply → /info'
        )
        return

    username = (
        f"@{target.username}"
        if target.username
        else "မရှိပါ"
    )

    warns = get_warning(
        update.effective_chat.id,
        target.id
    )

    bio = await get_user_bio(
        context,
        target.id
    )

    if not bio:
        bio = "မရှိပါ / မရရှိပါ"

    user_link = (
        f"https://t.me/{target.username}"
        if target.username
        else f"tg://user?id={target.id}"
    )

    text = chr(10).join([
        f"👤 Name : {(getattr(target, "first_name", "") or "") + (" " + getattr(target, "last_name", "") if getattr(target, "last_name", None) else "")}".strip(),
        f"🔹 Username : {username}",
        f"🆔 User ID : {target.id}",
        f"⚠️ Warning : {warns}/3",
        f"📝 Bio : {bio}",
        f"🔗 [User Link]({user_link})"
    ])

    await update.effective_message.reply_text(
        text,
        parse_mode="Markdown"
    )


# ==============================
# ⚠️ /warns
# ==============================

async def warns_command(update, context):
    if not await require_admin(update):
        return

    message = update.effective_message
    chat_id = update.effective_chat.id

    target = await resolve_target(update, context)

    if not target:
        await message.reply_text(
            "❌ Target User မတွေ့ပါ။\n\n"
            "အသုံးပြုပုံ:\n"
            "• Reply → /warns\n"
            "• /warns @username\n"
            "• /warns USER_ID"
        )
        return

    count = get_warning(chat_id, target.id)

    username = (
        f"@{target.username}"
        if target.username
        else "မရှိပါ"
    )

    await message.reply_text(
        "╭━━〔 ⚠️ WARNS 〕━━╮\n"
        "│\n"
        f"│ 👤 Name : {target.full_name}\n"
        f"│ 🔹 Username : {username}\n"
        f"│ 🆔 User ID : {target.id}\n"
        f"│ ⚠️ Warning : {count}/{MAX_WARNINGS}\n"
        "│\n"
        "╰━━━━━━━━━━━━━━━━━━╯"
    )


async def warn_command(update, context):
    if not await require_admin(update):
        return

    message = update.effective_message
    chat_id = update.effective_chat.id

    target = await resolve_target(update, context)

    if not target:
        await message.reply_text(
            "❌ Target User မတွေ့ပါ။\n\n"
            "အသုံးပြုပုံ:\n"
            "• Reply → /warn\n"
            "• /warn @username\n"
            "• /warn USER_ID"
        )
        return

    # /warn target ကို အတုအယောင် update မလုပ်ဘဲ
    # warning logic ကို တိုက်ရိုက်သုံးမယ်
    count = add_warning(chat_id, target.id)

    print(
        f"MANUAL WARNING: chat={chat_id} "
        f"user={target.id} count={count}"
    )

    if count < MAX_WARNINGS:
        await message.reply_text(
            "╭━━〔 ⚠️ WARNING 〕━━╮\n"
            "│\n"
            f"│ 👤 {target.full_name}\n"
            f"│ ⚠️ Warning : {count}/{MAX_WARNINGS}\n"
            "│\n"
            "╰━━━━━━━━━━━━━━━━╯"
        )
        return

    try:
        await mute_user(
            context,
            chat_id,
            target.id,
            30
        )

        await message.reply_text(
            "╭━━〔 🔇 AUTO MUTE 〕━━╮\n"
            "│\n"
            f"│ 👤 {target.full_name}\n"
            f"│ ⚠️ Warning : {MAX_WARNINGS}/{MAX_WARNINGS}\n"
            "│ 🔇 30 စက္ကန့် Mute လုပ်ထားပါတယ်။\n"
            "│ 🔊 30 စက္ကန့်ပြည့်ရင် Auto Unmute ဖြစ်ပါမယ်။\n"
            "│\n"
            "╰━━━━━━━━━━━━━━━━╯"
        )

        print(
            f"MANUAL AUTO MUTE SUCCESS: "
            f"user={target.id}"
        )

    except Exception as e:
        print(
            "MANUAL AUTO MUTE ERROR:",
            repr(e)
        )

async def unwarn_command(update, context):
    if not await require_admin(update):
        return

    message = update.effective_message
    chat_id = update.effective_chat.id

    target = await resolve_target(update, context)

    if not target:
        await message.reply_text(
            "❌ Target User မတွေ့ပါ။\n\n"
            "အသုံးပြုပုံ:\n"
            "• Reply → /unwarn\n"
            "• /unwarn @username\n"
            "• /unwarn USER_ID"
        )
        return

    current = get_warning(chat_id, target.id)

    if current <= 0:
        await message.reply_text(
            "ℹ️ ဒီ User မှာ Warning မရှိပါ။"
        )
        return

    new_count = current - 1

    if new_count == 0:
        db.execute(
            "DELETE FROM warnings WHERE chat_id = ? AND user_id = ?",
            (chat_id, target.id)
        )
    else:
        db.execute(
            """
            UPDATE warnings
            SET count = ?
            WHERE chat_id = ? AND user_id = ?
            """,
            (new_count, chat_id, target.id)
        )

    db.commit()

    await message.reply_text(
        "╭━━〔 ✅ UNWARN 〕━━╮\n"
        "│\n"
        f"│ 👤 User : {target.full_name}\n"
        f"│ ⚠️ Warning : {new_count}/{MAX_WARNINGS}\n"
        "│ 🔓 Warning ၁ ကြိမ် လျှော့ပေးပြီးပါပြီ။\n"
        "│\n"
        "╰━━━━━━━━━━━━━━━━━━╯"
    )




async def resolve_target(update, context, arg_index=0):
    """
    Resolve Telegram target safely.

    Supports:
    - Reply
    - USER_ID
    - @username / username
    - First name
    - Last name
    - Full name
    - Burmese Unicode names
    - Emoji-wrapped names
    - Names containing spaces
    """

    message = update.effective_message

    if not message:
        return None

    chat_id = update.effective_chat.id

    # =====================================================
    # 1. REPLY
    # =====================================================
    if message.reply_to_message:
        user = message.reply_to_message.from_user

        if user:
            try:
                cache_user(chat_id, user)
            except Exception:
                pass

            return user

    # =====================================================
    # 2. GET ARGUMENT
    # =====================================================
    args = context.args or []

    if len(args) <= arg_index:
        return None

    # IMPORTANT:
    # Join remaining arguments so full names work:
    #
    # /mute John Smith
    # /mute မိန်းလေး အောင်
    #
    raw = " ".join(args[arg_index:]).strip()

    if not raw:
        return None

    # =====================================================
    # 3. CLEAN ONLY OUTER DECORATIVE SYMBOLS
    #
    # DO NOT use [^\w]
    # because it destroys Burmese Unicode combining marks.
    # =====================================================

    search_name = raw.strip()

    # Remove @ only when it is at the beginning.
    search_name = search_name.lstrip("@").strip()

    # Remove common decorative emoji/symbols only
    # from the OUTSIDE of the name.
    #
    # Burmese Unicode characters are preserved.
    decorative = (
        "🍀🌿🌱🌳🌲🌴🌵🌷🌹🌺🌸🌼🌻"
        "❤️🩷🧡💛💚💙💜🖤🤍🤎"
        "✨⭐🌟💫🔥💥💯"
        "𒀱𒆜𖤍✦✧✪★☆"
        "【】「」『』《》<>[](){}"
        "༺༻꧁꧂"
    )

    search_name = search_name.strip(decorative).strip()

    if not search_name:
        return None

    print(
        f"🔎 Target search: {raw!r} -> {search_name!r}"
    )

    # =====================================================
    # 4. USER ID
    # =====================================================
    if re.fullmatch(r"-?\d+", search_name):

        uid = int(search_name)

        # Bot API first
        try:
            member = await context.bot.get_chat_member(
                chat_id,
                uid
            )

            if member and member.user:
                try:
                    cache_user(chat_id, member.user)
                except Exception:
                    pass

                return member.user

        except Exception as e:
            print(
                "⚠️ Bot API USER_ID error:",
                repr(e)
            )

        # Telethon fallback
        try:
            entity = await resolver.get_entity(uid)

            if entity and hasattr(entity, "id"):
                return entity

        except Exception as e:
            print(
                "⚠️ Telethon USER_ID error:",
                repr(e)
            )

        return None

    # =====================================================
    # 5. FIND CURRENT GROUP ENTITY
    # =====================================================
    group_entity = None

    try:
        async for dialog in resolver.iter_dialogs():

            try:
                if dialog.id == chat_id:
                    group_entity = dialog.entity
                    break

            except Exception:
                continue

    except Exception as e:
        print(
            "⚠️ Telethon dialog error:",
            repr(e)
        )

    if group_entity is None:
        print(
            "❌ Telethon group entity not found:",
            chat_id
        )
        return None

    # =====================================================
    # 6. DIRECT USERNAME SEARCH
    # =====================================================
    try:
        entity = await resolver.get_entity(search_name)

        if entity and hasattr(entity, "id"):

            try:
                cache_user(chat_id, entity)
            except Exception:
                pass

            return entity

    except Exception:
        pass

    # =====================================================
    # 7. NAME COMPARISON HELPER
    # =====================================================

    def clean_compare(value):
        if not value:
            return ""

        # IMPORTANT:
        # No Unicode normalization that removes Burmese marks.
        return " ".join(str(value).strip().split()).casefold()

    q = clean_compare(search_name)

    # =====================================================
    # 8. SEARCH GROUP MEMBERS
    # =====================================================
    try:

        async for user in resolver.iter_participants(
            group_entity,
            search=search_name
        ):

            if not user:
                continue

            first = (
                getattr(user, "first_name", None)
                or ""
            ).strip()

            last = (
                getattr(user, "last_name", None)
                or ""
            ).strip()

            username = (
                getattr(user, "username", None)
                or ""
            ).strip()

            full_name = f"{first} {last}".strip()

            candidates = [
                username,
                first,
                last,
                full_name
            ]

            for candidate in candidates:

                if clean_compare(candidate) == q:

                    try:
                        cache_user(chat_id, user)
                    except Exception:
                        pass

                    print(
                        "✅ Target found:",
                        full_name,
                        "|",
                        username,
                        "|",
                        user.id
                    )

                    return user

    except Exception as e:
        print(
            "⚠️ Telethon participant search error:",
            repr(e)
        )

    # =====================================================
    # 9. SECOND PASS — FULL MEMBER SCAN
    #
    # This handles Telegram search failing on:
    # - Burmese names
    # - Emoji names
    # - Decorative names
    # - Partial names
    # =====================================================
    try:

        async for user in resolver.iter_participants(
            group_entity
        ):

            if not user:
                continue

            first = (
                getattr(user, "first_name", None)
                or ""
            ).strip()

            last = (
                getattr(user, "last_name", None)
                or ""
            ).strip()

            username = (
                getattr(user, "username", None)
                or ""
            ).strip()

            full_name = f"{first} {last}".strip()

            values = [
                first,
                last,
                full_name,
                username
            ]

            for value in values:

                value_clean = clean_compare(value)

                if not value_clean:
                    continue

                # Exact match
                if value_clean == q:

                    try:
                        cache_user(chat_id, user)
                    except Exception:
                        pass

                    print(
                        "✅ Target found:",
                        full_name,
                        "|",
                        username,
                        "|",
                        user.id
                    )

                    return user

                # Partial match
                if (
                    q in value_clean
                    or value_clean in q
                ):

                    try:
                        cache_user(chat_id, user)
                    except Exception:
                        pass

                    print(
                        "✅ Target partial match:",
                        full_name,
                        "|",
                        username,
                        "|",
                        user.id
                    )

                    return user

    except Exception as e:
        print(
            "⚠️ Telethon full scan error:",
            repr(e)
        )

    print(
        f"❌ Target user not found: {raw!r} -> {search_name!r}"
    )

    return None


async def mute_command(update, context):
    if not await require_admin(update):
        return

    message = update.effective_message
    chat_id = update.effective_chat.id

    target = await resolve_target(update, context)

    if not target:
        await message.reply_text(
            "❌ Target User မတွေ့ပါ။\n\n"
            "အသုံးပြုပုံ:\n"
            "• Reply → /mute\n"
            "• /mute @username\n"
            "• /mute USER_ID"
        )
        return

    try:
        await mute_user(
            context,
            chat_id,
            target.id,
            3600
        )

        await message.reply_text(
            "╭━━〔 🔇 MUTE 〕━━╮\n"
            "│\n"
            f"│ 👤 User : {target.full_name}\n"
            "│ ⏱️ 1 နာရီ Mute လုပ်ထားပါတယ်။\n"
            "│\n"
            "╰━━━━━━━━━━━━━━━━━━╯"
        )

    except Exception as e:
        print("🔥 REAL MUTE ERROR:", type(e).__name__, repr(e))
        await message.reply_text(
            "❌ Mute လုပ်မရပါ။\n"
            "Bot ရဲ့ Restrict Members permission ကို စစ်ပါ။"
        )


async def tmute_command(update, context):
    if not await require_admin(update):
        return

    message = update.effective_message
    chat_id = update.effective_chat.id

    seconds = None
    target = None

    # /tmute SECONDS USER_ID or @username
    if len(context.args) >= 2:
        try:
            seconds = int(context.args[0])
        except ValueError:
            seconds = None

        target = await resolve_target(update, context, 1)

    # Reply + /tmute SECONDS
    elif len(context.args) >= 1 and message.reply_to_message:
        try:
            seconds = int(context.args[0])
        except ValueError:
            seconds = None

        target = await resolve_target(update, context)

    if not target or not seconds or seconds <= 0:
        await message.reply_text(
            "❌ Target User မတွေ့ပါ။\n\n"
            "အသုံးပြုပုံ:\n"
            "• Reply → /tmute 30\n"
            "• /tmute 30 @username\n"
            "• /tmute 30 USER_ID"
        )
        return

    try:
        await mute_user(
            context,
            chat_id,
            target.id,
            seconds
        )

        await message.reply_text(
            "╭━━〔 🔇 TMUTE 〕━━╮\n"
            "│\n"
            f"│ 👤 User : {target.full_name}\n"
            f"│ ⏱️ {seconds} စက္ကန့် Mute လုပ်ထားပါတယ်။\n"
            "│\n"
            "╰━━━━━━━━━━━━━━━━━━╯"
        )

    except Exception as e:
        print("🔥 REAL TMUTE ERROR:", type(e).__name__, repr(e))
        await message.reply_text(
            "❌ Mute လုပ်မရပါ။\n"
            "Bot ရဲ့ Restrict Members permission ကို စစ်ပါ။"
        )


async def unmute_command(update, context):
    if not await require_admin(update):
        return

    message = update.effective_message
    chat_id = update.effective_chat.id

    target = await resolve_target(update, context)

    if not target:
        await message.reply_text(
            "❌ Target User မတွေ့ပါ။\n\n"
            "အသုံးပြုပုံ:\n"
            "• Reply → /unmute\n"
            "• /unmute @username\n"
            "• /unmute USER_ID"
        )
        return

    try:
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        )

        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target.id,
            permissions=permissions
        )

        await message.reply_text(
            "╭━━〔 🔊 UNMUTE 〕━━╮\n"
            "│\n"
            f"│ 👤 User : {target.full_name}\n"
            "│ 🔊 Mute ပြန်ဖြုတ်ပြီးပါပြီ။\n"
            "│\n"
            "╰━━━━━━━━━━━━━━━━━━╯"
        )

    except Exception as e:
        print("🔥 REAL UNMUTE ERROR:", type(e).__name__, repr(e))
        await message.reply_text(
            "❌ Unmute လုပ်မရပါ။\n"
            "Bot ရဲ့ Restrict Members permission ကို စစ်ပါ။"
        )


async def ban_command(update, context):
    if not await require_admin(update):
        return

    message = update.effective_message
    chat_id = update.effective_chat.id

    target = await resolve_target(update, context)

    if not target:
        await message.reply_text(
            "❌ Target User မတွေ့ပါ။\n\n"
            "အသုံးပြုပုံ:\n"
            "• Reply → /ban\n"
            "• /ban @username\n"
            "• /ban USER_ID"
        )
        return

    try:
        await context.bot.ban_chat_member(
            chat_id=chat_id,
            user_id=target.id
        )

        await message.reply_text(
            "╭━━〔 🔨 BAN 〕━━╮\n"
            "│\n"
            f"│ 👤 User : {target.full_name}\n"
            "│ 🚫 Group မှ Ban လုပ်ပြီးပါပြီ။\n"
            "│\n"
            "╰━━━━━━━━━━━━━━━━━━╯"
        )

    except Exception as e:
        print("BAN ERROR:", repr(e))
        await message.reply_text(
            "❌ Ban လုပ်မရပါ။\n"
            "Bot ရဲ့ Ban Users permission ကို စစ်ပါ။"
        )


async def unban_command(update, context):
    if not await require_admin(update):
        return

    message = update.effective_message
    chat_id = update.effective_chat.id

    target = await resolve_target(update, context)

    if not target:
        await message.reply_text(
            "❌ Target User မတွေ့ပါ။\n\n"
            "အသုံးပြုပုံ:\n"
            "• Reply → /unban\n"
            "• /unban @username\n"
            "• /unban USER_ID"
        )
        return

    try:
        await context.bot.unban_chat_member(
            chat_id=chat_id,
            user_id=target.id,
            only_if_banned=True
        )

        await message.reply_text(
            "╭━━〔 🔓 UNBAN 〕━━╮\n"
            "│\n"
            f"│ 👤 User : {target.full_name}\n"
            "│ 🔓 Ban ပြန်ဖြုတ်ပြီးပါပြီ။\n"
            "│\n"
            "╰━━━━━━━━━━━━━━━━━━╯"
        )

    except Exception as e:
        print("UNBAN ERROR:", repr(e))
        await message.reply_text(
            "❌ Unban လုပ်မရပါ။\n"
            "User ID / Bot permission ကို စစ်ပါ။"
        )


async def help_command(
    update,
    context
):
    text = """╭━━━〔 🤖 𝗕𝗢𝗧 𝗛𝗘𝗟𝗣 〕━━━╮

⚙️  /settings
   Bot Settings ON / OFF

ℹ️  /info
   User Info ကြည့်ရန်

⚠️  /warn
   Warning ပေးရန်

🔄  /unwarn
   Warning လျှော့ရန်

📊  /warns
   Warning အရေအတွက်ကြည့်ရန်

🔇  /mute
   User Mute

⏱️  /tmute 60
   60 Seconds Mute

🔊  /unmute
   Mute ဖြုတ်ရန်

🚫  /ban
   User Ban

✅  /unban
   Ban ဖြုတ်ရန်

💬  𝗔𝗨𝗧𝗢 𝗥𝗘𝗣𝗟𝗬

➕  /addreply hi
   Message ကို Reply လုပ်ပြီး
   /addreply hi လို့ထည့်ရန်

📋  /replies
   Auto Reply List ကြည့်ရန်

🗑️  /delreply hi
   Auto Reply ဖျက်ရန်

📌  Text • Sticker • Photo
    Video • File • APK • Audio
    Voice • GIF တို့ကို Auto Reply
    အဖြစ်သိမ်းနိုင်ပါတယ်။

╰━━━━━━━━━━━━━━━━━━╯"""

    await update.effective_message.reply_text(
        text
    )
# ==============================
# 🚀 /start
# ==============================

async def start_command(
    update,
    context
):
    await update.effective_message.reply_text(
        "╭━━〔 🤖 STARTED 〕━━╮\n"
        "│\n"
        "│ ✅ Bot အလုပ်လုပ်နေပါပြီ။\n"
        "│\n"
        "│ 🆘 Command များကြည့်ရန်\n"
        "│ 👉 /help\n"
        "│\n"
        "╰━━━━━━━━━━━━━━━━━━╯"
    )
# ==============================
# 🔊 SCHEDULED AUTO UNMUTE
# ==============================

async def scheduled_auto_unmute(job):
    data = job.data

    chat_id = data["chat_id"]
    user_id = data["user_id"]

    permissions = ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
    )

    try:
        await job.get_bot().restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions
        )

    except Exception as e:
        print("Auto Unmute Error:", e)


# ==============================
# ❗ ERROR HANDLER
# ==============================

async def error_handler(
    update,
    context
):
    print(
        "Bot Error:",
        context.error
    )


# ==============================
# 👤 USER CACHE HANDLER
# ==============================

async def cache_user_handler(update, context):
    user = update.effective_user
    chat = update.effective_chat

    if not user or not chat:
        return

    try:
        cache_user(chat.id, user)
    except Exception as e:
        print("USER CACHE ERROR:", repr(e))


# ==============================
# 🚀 MAIN
# ==============================

ADMIN_ONLY_COMMANDS = {"settings", "warn", "unwarn", "warns", "mute", "tmute", "unmute", "ban", "unban", "addreply", "replies", "delreply"}

async def admin_command_guard(update, context):
    msg=update.effective_message
    if not msg or not msg.text:return
    cmd=msg.text.split()[0].split("@")[0].lstrip("/").lower()
    if cmd not in ADMIN_ONLY_COMMANDS:return
    if not await is_admin(update, update.effective_user.id):
        await msg.reply_text("⛔ 𝐀𝐂𝐂𝐄𝐒𝐒 𝐃𝐄𝐍𝐈𝐄𝐃 ⛔\n\n🔐 ခွင့်ပြုချက် မရှိပါ။\n\n👑 𝐎𝐖𝐍𝐄𝐑 • 🛡️ 𝐀𝐃𝐌𝐈𝐍\nသာလျှင် အသုံးပြုနိုင်ပါသည်။")
        from telegram.ext import ApplicationHandlerStop
        raise ApplicationHandlerStop

async def resolver_start(app):
    print("🔎 Username resolver connecting...")
    await resolver.start()
    print("✅ Username resolver connected")


async def resolver_stop(app):
    print("🔌 Username resolver stopping...")
    await resolver.disconnect()


def main():

    print("🤖 Bot is starting...")

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(resolver_start)
        .post_shutdown(resolver_stop)
        .build()
    )

    # ==========================
    # 🚀 BASIC COMMANDS
    # ==========================
    app.add_handler(MessageHandler(filters.COMMAND, admin_command_guard), group=-1)

    app.add_handler(
        MessageHandler(
            filters.ALL,
            cache_user_handler
        ),
        group=-2
    )

    # ==========================
    # 🤖 RESOLVER AUTO JOIN
    # ==========================
    app.add_handler(
        ChatMemberHandler(
            auto_join_resolver,
            ChatMemberHandler.MY_CHAT_MEMBER
        ),
        group=-3
    )

    app.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    # ==========================
    # ⚙️ SETTINGS
    # ==========================

    app.add_handler(
        CommandHandler(
            "settings",
            settings_command
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            settings_callback,
            pattern="^set_|^settings_refresh$"
        )
    )

    # ==========================
    # 👤 USER COMMANDS
    # ==========================

    app.add_handler(
        CommandHandler(
            "info",
            info_command
        )
    )

    app.add_handler(
        CommandHandler(
            "warns",
            warns_command
        )
    )

    app.add_handler(
        CommandHandler(
            "warn",
            warn_command
        )
    )

    app.add_handler(
        CommandHandler(
            "unwarn",
            unwarn_command
        )
    )

    # ==========================
    # 🔇 MUTE COMMANDS
    # ==========================

    app.add_handler(
        CommandHandler(
            "mute",
            mute_command
        )
    )

    app.add_handler(
        CommandHandler(
            "tmute",
            tmute_command
        )
    )

    app.add_handler(
        CommandHandler(
            "unmute",
            unmute_command
        )
    )

    # ==========================
    # 🚫 BAN COMMANDS
    # ==========================

    app.add_handler(
        CommandHandler(
            "ban",
            ban_command
        )
    )

    app.add_handler(
        CommandHandler(
            "unban",
            unban_command
        )
    )

    # ==========================
    # 💬 AUTO REPLY COMMANDS
    # ==========================

    app.add_handler(
        CommandHandler(
            "addreply",
            addreply_command
        )
    )

    app.add_handler(
        CommandHandler(
            "replies",
            replies_command
        )
    )

    app.add_handler(
        CommandHandler(
            "delreply",
            delreply_command
        )
    )

    # ==========================
    # 👋 JOIN / LEAVE
    # ==========================

    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            auto_join_resolver
        ),
        group=-3
    )

    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS
            | filters.StatusUpdate.LEFT_CHAT_MEMBER,
            member_update
        )
    )

    # ==========================
    # 🎥 VIDEO CHAT
    # ==========================

    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.VIDEO_CHAT_STARTED
            | filters.StatusUpdate.VIDEO_CHAT_ENDED,
            video_chat_handler
        )
    )

    # ==========================
    # 🤖 AUTO REPLY
    # ==========================

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            auto_reply_handler
        ),
        group=1
    )

    # ==========================
    # 🛡️ MODERATION
    # ==========================

    app.add_handler(
        MessageHandler(
            (
                filters.TEXT
                | filters.CAPTION
                | filters.FORWARDED
            )
            & ~filters.COMMAND,
            moderate_message
        )
    )

    # ==========================
    # ❗ ERROR
    # ==========================

    app.add_error_handler(
        error_handler
    )

    print("🤖 Bot is running...")

    app.run_polling(
        drop_pending_updates=True
    )


# ==============================
# ▶️ START BOT
# ==============================

if __name__ == "__main__":
    main()

