# -*- coding: utf-8 -*-
"""
start.py  (ستارت ينظّف العمليات المعلّقة + زر جديد)
مع تحسينات:
- تسجيل الأخطاء logging
- كاش مؤقت للتحقق من الاشتراك
- حماية من السبام
"""

import logging
import time
from telebot import types
from handlers import keyboards
from config import BOT_NAME, FORCE_SUB_CHANNEL_USERNAME
from services.wallet_service import register_user_if_not_exist

# ---- إعدادات الواجهة ----
START_BTN_TEXT = "🚀 ستارت جديد"
START_BTN_TEXT_SUB = "✅ تم الاشتراك"
SUB_BTN_TEXT = "🔔 اشترك الآن في القناة"

CB_START = "cb_start_main"
CB_CHECK_SUB = "cb_check_sub"

# ---- كاش اشتراك تيليجرام + Rate Limiting ----
_sub_status_cache = {}
_sub_status_ttl = 60  # ثانية (مدة بقاء حالة الاشتراك في الكاش)
_user_start_limit = {}
_rate_limit_seconds = 5  # عدد ثواني بين كل /start من نفس المستخدم

# ---- تنظيف العمليات المعلّقة ----
def _reset_user_flows(user_id: int):
    try:
        from handlers import internet_providers
    except Exception as e:
        logging.error(f"[start.py] import error: {e}")
        return

    try:
        internet_providers.user_net_state.pop(user_id, None)
    except Exception as e:
        logging.warning(f"[start.py] user_net_state cleanup error: {e}")

    try:
        po = getattr(internet_providers, "pending_orders", None)
        if isinstance(po, dict):
            for oid in list(po.keys()):
                try:
                    if po[oid].get("user_id") == user_id:
                        po.pop(oid, None)
                except Exception as e:
                    logging.warning(f"[start.py] pending_orders cleanup: {e}")
    except Exception as e:
        logging.warning(f"[start.py] pending_orders main cleanup: {e}")

# ---- لوحات الاشتراك ----
def _sub_inline_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    if FORCE_SUB_CHANNEL_USERNAME:
        kb.add(
            types.InlineKeyboardButton(
                SUB_BTN_TEXT,
                url=f"https://t.me/{FORCE_SUB_CHANNEL_USERNAME[1:]}"
            )
        )
    kb.add(types.InlineKeyboardButton(START_BTN_TEXT_SUB, callback_data=CB_CHECK_SUB))
    kb.add(types.InlineKeyboardButton(START_BTN_TEXT, callback_data=CB_START))
    return kb

def _welcome_inline_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton(START_BTN_TEXT, callback_data=CB_START))
    return kb

# ---- كاش تحقق الاشتراك ----
def is_user_subscribed(bot, user_id):
    now = time.time()
    # تحقق من الكاش أولاً
    cached = _sub_status_cache.get(user_id)
    if cached:
        status, last_check = cached
        if now - last_check < _sub_status_ttl:
            return status

    try:
        result = bot.get_chat_member(FORCE_SUB_CHANNEL_USERNAME, user_id)
        status = result.status in ["member", "creator", "administrator"]
        _sub_status_cache[user_id] = (status, now)
        return status
    except Exception as e:
        logging.error(f"[start.py] Error get_chat_member: {e}", exc_info=True)
        # نعتبره غير مشترك في حال فشل التحقق (أو غير متاح مؤقتاً)
        _sub_status_cache[user_id] = (False, now)
        return False

def register(bot, user_history):

    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        user_id = message.from_user.id
        now = time.time()

        # حماية سبام: Rate limiting
        last = _user_start_limit.get(user_id, 0)
        if now - last < _rate_limit_seconds:
            try:
                bot.send_message(message.chat.id, "يرجى الانتظار قبل إعادة المحاولة.")
            except Exception as e:
                logging.error(f"[start.py] rate limit send_message: {e}")
            return
        _user_start_limit[user_id] = now

        _reset_user_flows(user_id)

        # تحقق الاشتراك مع الكاش
        if FORCE_SUB_CHANNEL_USERNAME:
            if not is_user_subscribed(bot, user_id):
                try:
                    bot.send_message(
                        message.chat.id,
                        f"⚠️ للاستخدام الكامل لبوت {BOT_NAME}\nيرجى الاشتراك بالقناة أولاً.",
                        reply_markup=_sub_inline_kb()
                    )
                except Exception as e:
                    logging.error(f"[start.py] send sub msg: {e}")
                return

        # بعد الاشتراك أو إذا لم يكن هناك شرط اشتراك
        try:
            bot.send_message(
                message.chat.id,
                WELCOME_MESSAGE,
                parse_mode="Markdown",
                reply_markup=_welcome_inline_kb()
            )
        except Exception as e:
            logging.error(f"[start.py] send welcome msg: {e}")

        user_history[user_id] = []

    # ---- Callback: إعادة فحص الاشتراك ----
    @bot.callback_query_handler(func=lambda c: c.data == CB_CHECK_SUB)
    def cb_check_subscription(call):
        user_id = call.from_user.id
        _reset_user_flows(user_id)

        if FORCE_SUB_CHANNEL_USERNAME:
            if not is_user_subscribed(bot, user_id):
                try:
                    bot.answer_callback_query(call.id, "لم يتم العثور على اشتراك. اشترك ثم أعد المحاولة.", show_alert=True)
                except Exception as e:
                    logging.error(f"[start.py] answer cb_check_sub: {e}")
                return

        # لو وصلنا هنا، مشترك!
        try:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=WELCOME_MESSAGE,
                parse_mode="Markdown",
                reply_markup=_welcome_inline_kb()
            )
        except Exception as e:
            logging.error(f"[start.py] edit_message_text cb_check_sub: {e}")
        user_history[user_id] = []

    # ---- Callback: ستارت (القائمة الرئيسية) ----
    @bot.callback_query_handler(func=lambda c: c.data == CB_START)
    def cb_start_main(call):
        user_id = call.from_user.id
        name = getattr(call.from_user, "full_name", None) or call.from_user.first_name
        _reset_user_flows(user_id)

        try:
            register_user_if_not_exist(user_id, name)
        except Exception as e:
            logging.error(f"[start.py] register_user_if_not_exist: {e}")

        try:
            bot.answer_callback_query(call.id)
            bot.send_message(
                call.message.chat.id,
                "✨ تم تسجيلك بنجاح! هذه القائمة الرئيسية.",
                reply_markup=keyboards.main_menu()
            )
        except Exception as e:
            logging.error(f"[start.py] cb_start_main: {e}")

    # ---- توافقية: نصوص قديمة ----
    @bot.message_handler(func=lambda msg: msg.text == "🚀 ابدأ بالتسوق العالمي")
    def enter_main_menu(msg):
        user_id = msg.from_user.id
        name = getattr(msg.from_user, "full_name", None) or msg.from_user.first_name
        _reset_user_flows(user_id)

        try:
            register_user_if_not_exist(user_id, name)
            bot.send_message(
                msg.chat.id,
                "✨ تم تسجيلك بنجاح! هذه القائمة الرئيسية.",
                reply_markup=keyboards.main_menu()
            )
        except Exception as e:
            logging.error(f"[start.py] enter_main_menu: {e}")

    @bot.message_handler(func=lambda msg: msg.text == "🔄 ابدأ من جديد")
    def restart_user(msg):
        send_welcome(msg)

    @bot.message_handler(func=lambda msg: msg.text == "🌐 صفحتنا")
    def send_links(msg):
        user_id = msg.from_user.id
        user_history.setdefault(user_id, []).append("send_links")
        text = (
            "🌐 روابط صفحتنا:\n\n"
            "🔗 موقعنا الإلكتروني: https://example.com\n"
            "📘 فيسبوك: https://facebook.com/yourpage\n"
            "▶️ يوتيوب: https://youtube.com/yourchannel\n"
            "🎮 كيك: https://kick.com/yourchannel"
        )
        try:
            bot.send_message(msg.chat.id, text, reply_markup=keyboards.links_menu())
        except Exception as e:
            logging.error(f"[start.py] send_links: {e}")

    @bot.message_handler(func=lambda msg: msg.text == "⬅️ رجوع")
    def go_back(msg):
        _reset_user_flows(msg.from_user.id)
        try:
            bot.send_message(msg.chat.id, "⬅️ تم الرجوع للقائمة الرئيسية", reply_markup=keyboards.main_menu())
        except Exception as e:
            logging.error(f"[start.py] go_back: {e}")

# ---- رسالة الترحيب ----
WELCOME_MESSAGE = (
    f"مرحبًا بك في {BOT_NAME}, وجهتك الأولى للتسوق الإلكتروني!\n\n"
    "🚀 نحن هنا نقدم لك تجربة تسوق لا مثيل لها:\n"
    "💼 منتجات عالية الجودة.\n"
    "⚡ سرعة في التنفيذ.\n"
    "📞 دعم فني خبير تحت تصرفك.\n\n"
    "🌟 لماذا نحن الأفضل؟\n"
    "1️⃣ توفير منتجات رائعة بأسعار تنافسية.\n"
    "2️⃣ تجربة تسوق آمنة وسهلة.\n"
    "3️⃣ فريق محترف جاهز لخدمتك على مدار الساعة.\n\n"
    "🚨 *تحذيرات هامة لا يمكن تجاهلها!*\n"
    "1️⃣ أي معلومات خاطئة ترسلها... عليك تحمل مسؤوليتها.\n"
    "2️⃣ *سيتم حذف محفظتك* إذا لم تقم بأي عملية شراء خلال 40 يومًا.\n"
    "3️⃣ *لا تراسل الإدارة* إلا في حالة الطوارئ!\n\n"
    "🔔 *هل أنت جاهز؟* لأننا على استعداد تام لتلبية احتياجاتك!\n"
    "👇 اضغط على زر 🚀 للمتابعة."
)
