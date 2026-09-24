import os
import re
import sqlite3
import logging

from dotenv import load_dotenv

from telegram import Update, ChatPermissions
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN မတွေ့ပါ။ .env ဖိုင်ကို စစ်ပါ။")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# DATABASE
# =========================================================

DB_FILE = "luna.db"


def db():
    return sqlite3.connect(DB_FILE)


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            chat_id INTEGER,
            feature TEXT,
            enabled INTEGER DEFAULT 0,
            UNIQUE(chat_id, feature)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS auto_filters (
            chat_id INTEGER,
            trigger TEXT,
            reply TEXT,
            UNIQUE(chat_id, trigger)
        )
    """)

    conn.commit()
    conn.close()


def get_setting(chat_id, feature):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT enabled
        FROM settings
        WHERE chat_id=? AND feature=?
        """,
        (chat_id, feature),
    )

    row = cur.fetchone()
    conn.close()

    return bool(row[0]) if row else False


def set_setting(chat_id, feature, enabled):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO settings(chat_id, feature, enabled)
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id, feature)
        DO UPDATE SET enabled=excluded.enabled
        """,
        (chat_id, feature, int(enabled)),
    )

    conn.commit()
    conn.close()


# =========================================================
# ADMIN CHECK
# =========================================================

async def is_admin(update: Update):
    if not update.effective_chat or not update.effective_user:
        return False

    if update.effective_chat.type not in ("group", "supergroup"):
        return True

    member = await update.effective_chat.get_member(
        update.effective_user.id
    )

    return member.status in (
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    )


async def bot_is_admin(update: Update):
    member = await update.effective_chat.get_member(
        update.get_bot().id
    )

    return member.status in (
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    )


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = (
        "🤖 LUNA Group Management Bot\n\n"
        "✅ Bot အလုပ်လုပ်နေပါပြီ!\n\n"
        "📌 Commands\n"
        "/help\n"
        "/ban - User ကို Ban\n"
        "/kick - User ကို Kick\n"
        "/mute - User ကို Mute\n"
        "/unmute - User ကို Unmute\n\n"
        "🛡 Protection\n"
        "/nolinks on\n"
        "/nolinks off\n"
        "/noforwards on\n"
        "/noforwards off\n\n"
        "🤖 Auto Reply\n"
        "/filter add hello | မင်္ဂလာပါ 👋\n"
        "/filter del hello\n"
        "/filter list"
    )

    await update.message.reply_text(text)


# =========================================================
# HELP
# =========================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = (
        "🤖 LUNA BOT HELP\n\n"
        "👮 Moderation\n"
        "/ban - Reply လုပ်ပြီး Ban\n"
        "/kick - Reply လုပ်ပြီး Kick\n"
        "/mute - Reply လုပ်ပြီး Mute\n"
        "/unmute - Reply လုပ်ပြီး Unmute\n\n"
        "🛡 Protection\n"
        "/nolinks on\n"
        "/nolinks off\n"
        "/noforwards on\n"
        "/noforwards off\n\n"
        "🤖 Filter\n"
        "/filter add hello | မင်္ဂလာပါ 👋\n"
        "/filter del hello\n"
        "/filter list"
    )

    await update.message.reply_text(text)


# =========================================================
# GET REPLIED USER
# =========================================================

def get_target_user(update: Update):

    if not update.message:
        return None

    if not update.message.reply_to_message:
        return None

    return update.message.reply_to_message.from_user


# =========================================================
# BAN
# =========================================================

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update):
        return

    target = get_target_user(update)

    if not target:
        await update.message.reply_text(
            "❌ Ban လုပ်မယ့် User ရဲ့ message ကို Reply လုပ်ပြီး /ban ရိုက်ပါ။"
        )
        return

    try:
        await update.effective_chat.ban_member(target.id)

        await update.message.reply_text(
            f"🔨 {target.mention_html()} ကို Ban လုပ်ပြီးပါပြီ။",
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"Ban error: {e}")
        await update.message.reply_text(
            "❌ Ban မလုပ်နိုင်ပါဘူး။ Bot ကို Admin + Ban Users permission ပေးထားပါ။"
        )


# =========================================================
# UNBAN
# =========================================================

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update):
        return

    target = get_target_user(update)

    if not target:
        await update.message.reply_text(
            "❌ Unban လုပ်မယ့် User ရဲ့ message ကို Reply လုပ်ပြီး /unban ရိုက်ပါ။"
        )
        return

    try:
        await update.effective_chat.unban_member(
            target.id,
            only_if_banned=True,
        )

        await update.message.reply_text(
            f"✅ {target.mention_html()} ကို Unban လုပ်ပြီးပါပြီ။",
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"Unban error: {e}")
        await update.message.reply_text(
            "❌ Unban မလုပ်နိုင်ပါဘူး။"
        )


# =========================================================
# KICK
# =========================================================

async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update):
        return

    target = get_target_user(update)

    if not target:
        await update.message.reply_text(
            "❌ Kick လုပ်မယ့် User ရဲ့ message ကို Reply လုပ်ပြီး /kick ရိုက်ပါ။"
        )
        return

    try:
        await update.effective_chat.ban_member(target.id)

        await update.effective_chat.unban_member(
            target.id,
            only_if_banned=False,
        )

        await update.message.reply_text(
            f"👢 {target.mention_html()} ကို Kick လုပ်ပြီးပါပြီ။",
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"Kick error: {e}")
        await update.message.reply_text(
            "❌ Kick မလုပ်နိုင်ပါဘူး။ Bot ကို Ban Users permission ပေးထားပါ။"
        )


# =========================================================
# MUTE
# =========================================================

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update):
        return

    target = get_target_user(update)

    if not target:
        await update.message.reply_text(
            "❌ Mute လုပ်မယ့် User ရဲ့ message ကို Reply လုပ်ပြီး /mute ရိုက်ပါ။"
        )
        return

    try:
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=True,
            can_pin_messages=False,
            can_manage_topics=False,
        )

        await update.effective_chat.restrict_member(
            target.id,
            permissions=permissions,
        )

        await update.message.reply_text(
            f"🔇 {target.mention_html()} ကို Mute လုပ်ပြီးပါပြီ။",
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"Mute error: {e}")
        await update.message.reply_text(
            "❌ Mute မလုပ်နိုင်ပါဘူး။ Bot ကို Restrict Members permission ပေးထားပါ။"
        )


# =========================================================
# UNMUTE
# =========================================================

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update):
        return

    target = get_target_user(update)

    if not target:
        await update.message.reply_text(
            "❌ Unmute လုပ်မယ့် User ရဲ့ message ကို Reply လုပ်ပြီး /unmute ရိုက်ပါ။"
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
            can_add_web_page_previews=True,
            can_change_info=False,
            can_invite_users=True,
            can_pin_messages=False,
            can_manage_topics=False,
        )

        await update.effective_chat.restrict_member(
            target.id,
            permissions=permissions,
        )

        await update.message.reply_text(
            f"🔊 {target.mention_html()} ကို Unmute လုပ်ပြီးပါပြီ။",
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"Unmute error: {e}")
        await update.message.reply_text(
            "❌ Unmute မလုပ်နိုင်ပါဘူး။"
        )


# =========================================================
# LINK PROTECTION
# =========================================================

async def nolinks(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update):
        return

    if not context.args:
        status = get_setting(
            update.effective_chat.id,
            "nolinks",
        )

        await update.message.reply_text(
            f"🔗 No Links: {'ON 🟢' if status else 'OFF 🔴'}\n\n"
            "/nolinks on\n"
            "/nolinks off"
        )
        return

    value = context.args[0].lower()

    if value == "on":
        set_setting(
            update.effective_chat.id,
            "nolinks",
            True,
        )

        await update.message.reply_text(
            "🔗 No Links ကို ON လုပ်ပြီးပါပြီ။"
        )

    elif value == "off":
        set_setting(
            update.effective_chat.id,
            "nolinks",
            False,
        )

        await update.message.reply_text(
            "🔗 No Links ကို OFF လုပ်ပြီးပါပြီ။"
        )

    else:
        await update.message.reply_text(
            "/nolinks on\n/nolinks off"
        )


# =========================================================
# FORWARD PROTECTION
# =========================================================

async def noforwards(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update):
        return

    if not context.args:
        status = get_setting(
            update.effective_chat.id,
            "noforwards",
        )

        await update.message.reply_text(
            f"↪️ No Forwards: {'ON 🟢' if status else 'OFF 🔴'}\n\n"
            "/noforwards on\n"
            "/noforwards off"
        )
        return

    value = context.args[0].lower()

    if value == "on":
        set_setting(
            update.effective_chat.id,
            "noforwards",
            True,
        )

        await update.message.reply_text(
            "↪️ No Forwards ကို ON လုပ်ပြီးပါပြီ။"
        )

    elif value == "off":
        set_setting(
            update.effective_chat.id,
            "noforwards",
            False,
        )

        await update.message.reply_text(
            "↪️ No Forwards ကို OFF လုပ်ပြီးပါပြီ။"
        )

    else:
        await update.message.reply_text(
            "/noforwards on\n/noforwards off"
        )


# =========================================================
# FILTER COMMAND
# =========================================================

async def filter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not await is_admin(update):
        return

    if not context.args:
        await update.message.reply_text(
            "🤖 FILTER\n\n"
            "ထည့်ရန်:\n"
            "/filter add hello | မင်္ဂလာပါ 👋\n\n"
            "ဖျက်ရန်:\n"
            "/filter del hello\n\n"
            "ကြည့်ရန်:\n"
            "/filter list"
        )
        return

    action = context.args[0].lower()

    # ---------------- ADD ----------------

    if action == "add":

        data = " ".join(context.args[1:])

        if "|" not in data:
            await update.message.reply_text(
                "❌ Format မှားနေပါတယ်။\n\n"
                "/filter add hello | မင်္ဂလာပါ 👋"
            )
            return

        trigger, reply = data.split("|", 1)

        trigger = trigger.strip().lower()
        reply = reply.strip()

        if not trigger or not reply:
            await update.message.reply_text(
                "❌ Trigger နဲ့ Reply နှစ်ခုလုံး ထည့်ပါ။"
            )
            return

        conn = db()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO auto_filters(chat_id, trigger, reply)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id, trigger)
            DO UPDATE SET reply=excluded.reply
            """,
            (
                update.effective_chat.id,
                trigger,
                reply,
            ),
        )

        conn.commit()
        conn.close()

        await update.message.reply_text(
            "✅ Filter ထည့်ပြီးပါပြီ!\n\n"
            f"🔹 Trigger: {trigger}\n"
            f"🔹 Reply: {reply}"
        )

        return

    # ---------------- DELETE ----------------

    if action == "del":

        if len(context.args) < 2:
            await update.message.reply_text(
                "/filter del hello"
            )
            return

        trigger = " ".join(
            context.args[1:]
        ).strip().lower()

        conn = db()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM auto_filters
            WHERE chat_id=? AND trigger=?
            """,
            (
                update.effective_chat.id,
                trigger,
            ),
        )

        deleted = cur.rowcount

        conn.commit()
        conn.close()

        if deleted:
            await update.message.reply_text(
                f"🗑️ {trigger} Filter ဖျက်ပြီးပါပြီ။"
            )
        else:
            await update.message.reply_text(
                "❌ အဲ့ဒီ Filter မတွေ့ပါဘူး။"
            )

        return

    # ---------------- LIST ----------------

    if action == "list":

        conn = db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT trigger, reply
            FROM auto_filters
            WHERE chat_id=?
            ORDER BY trigger
            """,
            (update.effective_chat.id,),
        )

        rows = cur.fetchall()

        conn.close()

        if not rows:
            await update.message.reply_text(
                "📭 Filter မရှိသေးပါဘူး။"
            )
            return

        text = "🤖 AUTO REPLY FILTERS\n\n"

        for trigger, reply in rows:
            text += f"🔹 {trigger} → {reply}\n"

        await update.message.reply_text(text)

        return

    await update.message.reply_text(
        "❌ Command မမှန်ပါဘူး။\n\n"
        "/filter add hello | မင်္ဂလာပါ 👋\n"
        "/filter del hello\n"
        "/filter list"
    )


# =========================================================
# MESSAGE SYSTEM
# =========================================================

async def message_system(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    chat_id = update.effective_chat.id

    # ---------------- LINK PROTECTION ----------------

    if (
        get_setting(chat_id, "nolinks")
        and update.effective_user
        and not await is_admin(update)
    ):

        text = update.message.text or update.message.caption or ""

        link_pattern = r"(https?://|www\.|t\.me/|telegram\.me/)"

        if re.search(link_pattern, text, re.IGNORECASE):

            try:
                await update.message.delete()

                await context.bot.send_message(
                    chat_id,
                    "⚠️ Link မပို့ရပါ။ Message ကို ဖျက်လိုက်ပါတယ်။",
                )

            except Exception as e:
                logger.error(f"Link delete error: {e}")

            return

    # ---------------- FORWARD PROTECTION ----------------

    if (
        get_setting(chat_id, "noforwards")
        and update.effective_user
        and not await is_admin(update)
    ):

        if (
            update.message.forward_origin
            or update.message.forward_from
            or update.message.forward_from_chat
        ):

            try:
                await update.message.delete()

                await context.bot.send_message(
                    chat_id,
                    "⚠️ Forward မပို့ရပါ။ Message ကို ဖျက်လိုက်ပါတယ်။",
                )

            except Exception as e:
                logger.error(f"Forward delete error: {e}")

            return

    # ---------------- AUTO REPLY ----------------

    text = update.message.text

    if not text:
        return

    trigger = text.strip().lower()

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT reply
        FROM auto_filters
        WHERE chat_id=? AND trigger=?
        """,
        (
            chat_id,
            trigger,
        ),
    )

    row = cur.fetchone()

    conn.close()

    if row:
        try:
            await update.message.reply_text(row[0])
        except Exception as e:
            logger.error(f"Auto reply error: {e}")


# =========================================================
# MAIN
# =========================================================

def main():

    init_db()

    print("🤖 LUNA Group Management Bot စတင်အလုပ်လုပ်နေပါပြီ...")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("help", help_command)
    )

    app.add_handler(
        CommandHandler("ban", ban)
    )

    app.add_handler(
        CommandHandler("unban", unban)
    )

    app.add_handler(
        CommandHandler("kick", kick)
    )

    app.add_handler(
        CommandHandler("mute", mute)
    )

    app.add_handler(
        CommandHandler("unmute", unmute)
    )

    app.add_handler(
        CommandHandler("nolinks", nolinks)
    )

    app.add_handler(
        CommandHandler("noforwards", noforwards)
    )

    app.add_handler(
        CommandHandler("filter", filter_command)
    )

    # Normal Messages

    app.add_handler(
        MessageHandler(
            filters.ALL,
            message_system,
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()
