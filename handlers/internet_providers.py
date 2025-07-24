from telebot import types
from services.wallet_service import (
    register_user_if_not_exist,
    add_purchase,
    get_balance,
    has_sufficient_balance,
    deduct_balance,
)
from config import ADMIN_MAIN_ID
from services.queue_service import add_pending_request, process_queue, delete_pending_request, get_table
import logging
import re

# ============================
#        الثوابت
# ============================
INTERNET_PROVIDERS = [
    "تراسل", "أم تي أن", "سيرياتيل", "آية", "سوا", "رن نت", "سما نت", "أمنية",
    "ناس", "هايبر نت", "MTS", "يارا", "دنيا", "آينت"
]

INTERNET_SPEEDS = [
    {"label": "1 ميغا", "price": 19500},
    {"label": "2 ميغا", "price": 25000},
    {"label": "4 ميغا", "price": 39000},
    {"label": "8 ميغا", "price": 65000},
    {"label": "16 ميغا", "price": 84000},
]

COMMISSION_PER_5000 = 600
user_net_state = {}  # {user_id: {step, provider, speed, price, phone}}
_PHONE_RE = re.compile(r"[+\d]+")

# ============================
#   دوال مساعدة
# ============================
def calculate_commission(amount: int) -> int:
    if amount <= 0:
        return 0
    blocks = (amount + 5000 - 1) // 5000
    return blocks * COMMISSION_PER_5000


def _provider_inline_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    btns = [
        types.InlineKeyboardButton(f"🌐 {name}", callback_data=f"iprov:{name}")
        for name in INTERNET_PROVIDERS
    ]
    if btns:
        kb.add(*btns)
    kb.add(types.InlineKeyboardButton("❌ إلغاء", callback_data="icancel"))
    return kb


def _speeds_inline_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    for idx, speed in enumerate(INTERNET_SPEEDS):
        kb.add(
            types.InlineKeyboardButton(
                text=f"{speed['label']} - {speed['price']:,} ل.س",
                callback_data=f"ispeed:{idx}"
            )
        )
    kb.add(types.InlineKeyboardButton("⬅️ رجوع", callback_data="iback_prov"))
    return kb


def _confirm_inline_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("✅ تأكيد", callback_data="iconfirm"))
    kb.add(types.InlineKeyboardButton("⬅️ تعديل", callback_data="iback_speed"))
    kb.add(types.InlineKeyboardButton("❌ إلغاء", callback_data="icancel"))
    return kb


def _normalize_phone(txt: str) -> str:
    clean = txt.replace(" ", "").replace("-", "").replace("_", "")
    return ''.join(_PHONE_RE.findall(clean))

# ============================
#   تسجيل معالجات الإنترنت
# ============================

def register(bot):
    @bot.message_handler(func=lambda m: m.text == "🌐 دفع مزودات الإنترنت ADSL")
    def open_net_menu(msg):
        bot.send_message(
            msg.chat.id,
            "⚠️ اختر مزود الإنترنت:\n💸 عمولة لكل 5000 ل.س = 600 ل.س",
            reply_markup=_provider_inline_kb()
        )
        user_net_state[msg.from_user.id] = {"step": "choose_provider"}

    @bot.callback_query_handler(func=lambda c: c.data.startswith("iprov:"))
    def cb_choose_provider(call):
        user_id = call.from_user.id
        provider = call.data.split(":", 1)[1]
        if provider not in INTERNET_PROVIDERS:
            bot.answer_callback_query(call.id, "خيار غير صالح.")
            return
        user_net_state[user_id] = {"step": "choose_speed", "provider": provider}
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="⚡ اختر السرعة المطلوبة:\n💸 عمولة لكل 5000 ل.س = 600 ل.س",
            reply_markup=_speeds_inline_kb()
        )

    @bot.callback_query_handler(func=lambda c: c.data == "iback_prov")
    def cb_back_to_prov(call):
        user_id = call.from_user.id
        user_net_state[user_id] = {"step": "choose_provider"}
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="⚠️ اختر مزود الإنترنت:\n💸 عمولة لكل 5000 ل.س = 600 ل.س",
            reply_markup=_provider_inline_kb()
        )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("ispeed:"))
    def cb_choose_speed(call):
        user_id = call.from_user.id
        idx = int(call.data.split(":", 1)[1])
        speed = INTERNET_SPEEDS[idx]
        st = user_net_state.setdefault(user_id, {})
        st.update({"step": "enter_phone", "speed": speed["label"], "price": speed["price"]})
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.message.chat.id,
            "📱 أرسل رقم الهاتف (مع رمز المحافظة، مثال: 011XXXXXXX).",
        )

    @bot.callback_query_handler(func=lambda c: c.data == "iback_speed")
    def cb_back_to_speed(call):
        user_id = call.from_user.id
        user_net_state[user_id]["step"] = "choose_speed"
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="⚡ اختر السرعة المطلوبة:\n💸 عمولة لكل 5000 ل.س = 600 ل.س",
            reply_markup=_speeds_inline_kb()
        )

    @bot.callback_query_handler(func=lambda c: c.data == "icancel")
    def cb_cancel(call):
        user_net_state.pop(call.from_user.id, None)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="تم الإلغاء. أرسل /start للعودة.",
        )

    @bot.message_handler(func=lambda m: user_net_state.get(m.from_user.id, {}).get("step") == "enter_phone")
    def handle_phone_entry(msg):
        user_id = msg.from_user.id
        phone = _normalize_phone(msg.text)
        if len(phone) < 5:
            return bot.reply_to(msg, "⚠️ رقم غير صالح.")
        st = user_net_state[user_id]
        st.update({"step": "confirm", "phone": phone})
        price = st["price"]
        comm = calculate_commission(price)
        total = price + comm
        summary = (
            f"📦 تفاصيل الطلب:\n"
            f"مزود: {st['provider']}\n"
            f"سرعة: {st['speed']}\n"
            f"السعر: {price:,} ل.س\n"
            f"العمولة: {comm:,} ل.س\n"
            f"إجمالي: {total:,} ل.س\n"
            f"رقم: {phone}"
        )
        bot.send_message(
            msg.chat.id,
            summary,
            reply_markup=_confirm_inline_kb()
        )

    @bot.callback_query_handler(func=lambda c: c.data == "iconfirm")
    def cb_confirm(call):
        user_id = call.from_user.id
        st = user_net_state.get(user_id)
        if not st or st.get("step") != "confirm":
            return bot.answer_callback_query(call.id, "انتهت صلاحية الطلب.", show_alert=True)
        price = st["price"]
        comm = calculate_commission(price)
        total = price + comm
        summary = (
            f"📥 طلب جديد (إنترنت):\n"
            f"👤 المستخدم: {user_id}\n"
            f"🌐 مزود: {st['provider']}\n"
            f"⚡ سرعة: {st['speed']}\n"
            f"📱 رقم: {st['phone']}\n"
            f"💰 {price:,} + عمولة {comm:,} = {total:,} ل.س"
        )
        add_pending_request(
            user_id=user_id,
            username=call.from_user.username,
            request_text=summary,
            payload={
                "type": "internet_provider",
                "provider": st['provider'],
                "speed": st['speed'],
                "phone": st['phone'],
                "price": price,
                "commission": comm,
                "total": total
            }
        )
        process_queue(bot)
        bot.send_message(
            call.message.chat.id,
            "✅ تم إرسال طلبك للإدارة، بانتظار الموافقة."
        )
