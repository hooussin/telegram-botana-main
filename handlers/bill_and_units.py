from telebot import types
import math
import logging
from database.db import get_table
from services.wallet_service import (
    get_balance,
    deduct_balance,
    add_balance,
    register_user_if_not_exist,
    add_purchase,
    has_sufficient_balance,
)
from config import ADMIN_MAIN_ID
from services.queue_service import add_pending_request

# --- قوائم المنتجات (وحدات) وأسعارها ---
SYRIATEL_UNITS = [
    {"name": "1000 وحدة", "price": 1200},
    {"name": "1500 وحدة", "price": 1800},
    {"name": "2013 وحدة", "price": 2400},
    {"name": "3068 وحدة", "price": 3682},
    {"name": "4506 وحدة", "price": 5400},
    {"name": "5273 وحدة", "price": 6285},
    {"name": "7190 وحدة", "price": 8628},
    {"name": "9587 وحدة", "price": 11500},
    {"name": "13039 وحدة", "price": 15500},
]

MTN_UNITS = [
    {"name": "1000 وحدة", "price": 1200},
    {"name": "5000 وحدة", "price": 6000},
    {"name": "7000 وحدة", "price": 8400},
    {"name": "10000 وحدة", "price": 12000},
    {"name": "15000 وحدة", "price": 18000},
    {"name": "20000 وحدة", "price": 24000},
    {"name": "23000 وحدة", "price": 27600},
    {"name": "30000 وحدة", "price": 36000},
    {"name": "36000 وحدة", "price": 43200},
]

# الحالة المؤقتة للمستخدمين
user_states: dict[int, dict] = {}

# ===================== أدوات مساعدة =====================

def make_inline_buttons(*buttons):
    kb = types.InlineKeyboardMarkup()
    for text, data in buttons:
        kb.add(types.InlineKeyboardButton(text, callback_data=data))
    return kb


def _unit_label(unit: dict) -> str:
    return f"{unit['name']} - {unit['price']:,} ل.س"

# =======================================================

def register_bill_and_units(bot, history):
    """تسجيل خدمات وحدات وفواتير سيرياتيل وMTN"""

    @bot.message_handler(func=lambda msg: msg.text == "💳 تحويل وحدات فاتورة سوري")
    def open_main_menu(msg):
        user_id = msg.from_user.id
        history.setdefault(user_id, []).append("units_bills_menu")
        user_states[user_id] = {"step": None}
        bot.send_message(msg.chat.id, "اختر الخدمة:", reply_markup=units_bills_menu_inline())

    @bot.callback_query_handler(func=lambda call: call.data.startswith("ubm:"))
    def ubm_router(call):
        action = call.data.split(":", 1)[1]
        chat_id = call.message.chat.id
        user_id = call.from_user.id

        if action == "syr_units":
            user_states[user_id] = {"step": "select_syr_unit"}
            _send_syr_units_page(chat_id, page=0, message_id=call.message.message_id)
        elif action == "syr_bill":
            user_states[user_id] = {"step": "syr_bill_number"}
            kb = make_inline_buttons(("❌ إلغاء", "cancel_all"))
            bot.edit_message_text("📱 أدخل رقم سيرياتيل المراد دفع فاتورته:", chat_id, call.message.message_id, reply_markup=kb)
        elif action == "mtn_units":
            user_states[user_id] = {"step": "select_mtn_unit"}
            _send_mtn_units_page(chat_id, page=0, message_id=call.message.message_id)
        elif action == "mtn_bill":
            user_states[user_id] = {"step": "mtn_bill_number"}
            kb = make_inline_buttons(("❌ إلغاء", "cancel_all"))
            bot.edit_message_text("📱 أدخل رقم MTN المراد دفع فاتورته:", chat_id, call.message.message_id, reply_markup=kb)
        elif action == "back":
            from keyboards import main_menu as _main_menu
            bot.edit_message_text("⬅️ رجوع", chat_id, call.message.message_id)
            bot.send_message(chat_id, "اختر من القائمة:", reply_markup=_main_menu())
        bot.answer_callback_query(call.id)

    def _send_syr_units_page(chat_id, page: int, message_id: int | None = None):
        items = [(idx, _unit_label(u)) for idx, u in enumerate(SYRIATEL_UNITS)]
        kb, pages = _build_paged_inline_keyboard(items, page, page_size=5, prefix="syrunits", back_data="ubm:back")
        text = f"اختر كمية الوحدات (صفحة {page+1}/{pages}):"
        if message_id:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=kb)
        else:
            bot.send_message(chat_id, text, reply_markup=kb)

    def _send_mtn_units_page(chat_id, page: int, message_id: int | None = None):
        items = [(idx, _unit_label(u)) for idx, u in enumerate(MTN_UNITS)]
        kb, pages = _build_paged_inline_keyboard(items, page, page_size=5, prefix="mtnunits", back_data="ubm:back")
        text = f"اختر كمية الوحدات (صفحة {page+1}/{pages}):"
        if message_id:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=kb)
        else:
            bot.send_message(chat_id, text, reply_markup=kb)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("syrunits:"))
    def syr_units_inline_handler(call):
        _, action, val = call.data.split(":")
        chat_id = call.message.chat.id
        user_id = call.from_user.id
        if action == "page":
            _send_syr_units_page(chat_id, int(val), call.message.message_id)
        elif action == "sel":
            unit = SYRIATEL_UNITS[int(val)]
            user_states[user_id] = {"step": "syr_unit_number", "unit": unit}
            kb = make_inline_buttons(("❌ إلغاء", "cancel_all"))
            bot.edit_message_text("📱 أدخل الرقم أو الكود:", chat_id, call.message.message_id, reply_markup=kb)
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("mtnunits:"))
    def mtn_units_inline_handler(call):
        _, action, val = call.data.split(":")
        chat_id = call.message.chat.id
        user_id = call.from_user.id
        if action == "page":
            _send_mtn_units_page(chat_id, int(val), call.message.message_id)
        elif action == "sel":
            unit = MTN_UNITS[int(val)]
            user_states[user_id] = {"step": "mtn_unit_number", "unit": unit}
            kb = make_inline_buttons(("❌ إلغاء", "cancel_all"))
            bot.edit_message_text("📱 أدخل الرقم أو الكود:", chat_id, call.message.message_id, reply_markup=kb)
        bot.answer_callback_query(call.id)

    @bot.message_handler(func=lambda msg: msg.text == "🔴 وحدات سيرياتيل")
    def syr_units_menu(msg):
        user_id = msg.from_user.id
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        for u in SYRIATEL_UNITS:
            kb.add(types.KeyboardButton(_unit_label(u)))
        kb.add(types.KeyboardButton("⬅️ رجوع"))
        user_states[user_id] = {"step": "select_syr_unit"}
        bot.send_message(msg.chat.id, "اختر كمية الوحدات:", reply_markup=kb)

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "select_syr_unit")
    def syr_unit_select(msg):
        user_id = msg.from_user.id
        unit = next((u for u in SYRIATEL_UNITS if _unit_label(u) == msg.text), None)
        if not unit:
            return
        user_states[user_id] = {"step": "syr_unit_final", "unit": unit}
        kb = make_inline_buttons(("✅ تأكيد", "syr_unit_final_confirm"), ("❌ إلغاء", "cancel_all"))
        bot.send_message(msg.chat.id, f"تأكيد طلب {unit['name']}؟", reply_markup=kb)

    @bot.callback_query_handler(func=lambda call: call.data == "syr_unit_final_confirm")
    def syr_unit_final_confirm(call):
        user_id = call.from_user.id
        unit = user_states[user_id]["unit"]
        summary = (
            f"🔴 طلب وحدات سيرياتيل:\n"
            f"👤 المستخدم: {user_id}\n"
            f"📱 الرقم/الكود: {user_states[user_id].get('number','')}\n"
            f"💵 الكمية: {unit['name']}\n"
            f"💰 السعر: {unit['price']:,} ل.س\n"
            f"✅ بانتظار موافقة الإدارة"
        )
        add_pending_request(user_id, call.from_user.username, summary)
        bot.send_message(call.message.chat.id, "✅ تم إرسال الطلب للإدارة، بانتظار الموافقة.")

    @bot.callback_query_handler(func=lambda call: call.data == "mtn_unit_final_confirm")
    def mtn_unit_final_confirm(call):
        user_id = call.from_user.id
        unit = user_states[user_id]["unit"]
        summary = (
            f"🟡 طلب وحدات MTN:\n"
            f"👤 المستخدم: {user_id}\n"
            f"📱 الرقم/الكود: {user_states[user_id].get('number','')}\n"
            f"💵 الكمية: {unit['name']}\n"
            f"💰 السعر: {unit['price']:,} ل.س\n"
            f"✅ بانتظار موافقة الإدارة"
        )
        add_pending_request(user_id, call.from_user.username, summary)
        bot.send_message(call.message.chat.id, "✅ تم إرسال الطلب للإدارة، بانتظار الموافقة.")

    @bot.callback_query_handler(func=lambda call: call.data == "final_confirm_syr_bill")
    def final_confirm_syr_bill(call):
        user_id = call.from_user.id
        amt = user_states[user_id].get('amount', 0)
        fee = user_states[user_id].get('fee', 0)
        total = amt + fee
        balance = get_balance(user_id)
        if balance < total:
            bot.send_message(
                call.message.chat.id,
                f"❌ لا يوجد لديك رصيد كافٍ.\nرصيدك الحالي: {balance:,}
