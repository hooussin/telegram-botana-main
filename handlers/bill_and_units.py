import math
from datetime import datetime
import logging
from telebot import types
from database.db import get_table
from services.wallet_service import get_balance, register_user_if_not_exist, add_balance
from config import ADMIN_MAIN_ID
from services.queue_service import add_pending_request

# --- قوائم الوحدات وأسعارها ---
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

# حالة المستخدمين المؤقتة
user_states: dict[int, dict] = {}

# ===== أدوات مساعدة لبناء الأزرار =====
def make_inline_buttons(*buttons):
    kb = types.InlineKeyboardMarkup()
    for text, data in buttons:
        kb.add(types.InlineKeyboardButton(text, callback_data=data))
    return kb

def _unit_label(unit: dict) -> str:
    return f"{unit['name']} - {unit['price']:,} ل.س"

def units_bills_menu_inline():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔴 وحدات سيرياتيل", callback_data="ubm:syr_units"))
    kb.add(types.InlineKeyboardButton("🔴 فاتورة سيرياتيل", callback_data="ubm:syr_bill"))
    kb.add(types.InlineKeyboardButton("🟡 وحدات MTN", callback_data="ubm:mtn_units"))
    kb.add(types.InlineKeyboardButton("🟡 فاتورة MTN", callback_data="ubm:mtn_bill"))
    kb.add(types.InlineKeyboardButton("⬅️ رجوع", callback_data="ubm:back"))
    return kb

def _build_paged_inline_keyboard(items, page: int, page_size: int, prefix: str, back_data: str | None):
    total = len(items)
    pages = max(1, math.ceil(total / page_size))
    page = max(0, min(page, pages - 1))
    start, end = page * page_size, (page + 1) * page_size
    kb = types.InlineKeyboardMarkup()
    for idx, label in items[start:end]:
        kb.add(types.InlineKeyboardButton(label, callback_data=f"{prefix}:sel:{idx}"))
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("◀️", callback_data=f"{prefix}:page:{page-1}"))
    nav.append(types.InlineKeyboardButton(f"{page+1}/{pages}", callback_data=f"{prefix}:noop"))
    if page < pages - 1:
        nav.append(types.InlineKeyboardButton("▶️", callback_data=f"{prefix}:page:{page+1}"))
    if nav:
        kb.row(*nav)
    if back_data:
        kb.add(types.InlineKeyboardButton("🔙 رجوع", callback_data=back_data))
    return kb, pages

# ===== تسجيل الهاندلرز =====
def register_bill_and_units(bot, history):
    @bot.message_handler(func=lambda msg: msg.text == "💳 تحويل وحدات فاتورة سوري")
    def open_main_menu(msg):
        uid = msg.from_user.id
        history.setdefault(uid, []).append("units_bills_menu")
        user_states[uid] = {"step": None}
        bot.send_message(msg.chat.id, "اختر الخدمة:", reply_markup=units_bills_menu_inline())

    @bot.callback_query_handler(func=lambda call: call.data.startswith("ubm:"))
    def ubm_router(call):
        uid, cid = call.from_user.id, call.message.chat.id
        action = call.data.split(":", 1)[1]
        if action == "syr_units":
            user_states[uid] = {"step": "select_syr_unit"}
            _send_syr_units_page(cid, 0, call.message.message_id)
        elif action == "syr_bill":
            user_states[uid] = {"step": "syr_bill_number"}
            bot.edit_message_text(
                "📱 أدخل رقم سيرياتيل:", cid, call.message.message_id,
                reply_markup=make_inline_buttons(("❌ إلغاء", "cancel_all"))
            )
        elif action == "mtn_units":
            user_states[uid] = {"step": "select_mtn_unit"}
            _send_mtn_units_page(cid, 0, call.message.message_id)
        elif action == "mtn_bill":
            user_states[uid] = {"step": "mtn_bill_number"}
            bot.edit_message_text(
                "📱 أدخل رقم MTN:", cid, call.message.message_id,
                reply_markup=make_inline_buttons(("❌ إلغاء", "cancel_all"))
            )
        elif action == "back":
            from keyboards import main_menu as _main_menu
            bot.edit_message_text("⬅️ رجوع", cid, call.message.message_id)
            bot.send_message(cid, "اختر:", reply_markup=_main_menu())
        bot.answer_callback_query(call.id)

    PAGE_SIZE = 5
    def _send_syr_units_page(chat_id, page, message_id=None):
        items = list(enumerate([_unit_label(u) for u in SYRIATEL_UNITS]))
        kb, pages = _build_paged_inline_keyboard(items, page, PAGE_SIZE, "syrunits", "ubm:back")
        text = f"اختر وحدات سيرياتيل (صفحة {page+1}/{pages}):"
        if message_id:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=kb)
        else:
            bot.send_message(chat_id, text, reply_markup=kb)

    def _send_mtn_units_page(chat_id, page, message_id=None):
        items = list(enumerate([_unit_label(u) for u in MTN_UNITS]))
        kb, pages = _build_paged_inline_keyboard(items, page, PAGE_SIZE, "mtnunits", "ubm:back")
        text = f"اختر وحدات MTN (صفحة {page+1}/{pages}):"
        if message_id:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=kb)
        else:
            bot.send_message(chat_id, text, reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("syrunits:"))
    def syr_units_inline_handler(c):
        _, action, val = c.data.split(":")
        uid, cid = c.from_user.id, c.message.chat.id
        if action == "page":
            _send_syr_units_page(cid, int(val), c.message.message_id)
        elif action == "sel":
            unit = SYRIATEL_UNITS[int(val)]
            user_states[uid] = {"step": "syr_unit_final", "unit": unit}
            bot.edit_message_text(
                "📱 أدخل الرقم:", cid, c.message.message_id,
                reply_markup=make_inline_buttons(("✅ تأكيد", "syr_unit_final_confirm"), ("❌ إلغاء", "cancel_all"))
            )
        bot.answer_callback_query(c.id)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("mtnunits:"))
    def mtn_units_inline_handler(c):
        _, action, val = c.data.split(":")
        uid, cid = c.from_user.id, c.message.chat.id
        if action == "page":
            _send_mtn_units_page(cid, int(val), c.message.message_id)
        elif action == "sel":
            unit = MTN_UNITS[int(val)]
            user_states[uid] = {"step": "mtn_unit_final", "unit": unit}
            bot.edit_message_text(
                "📱 أدخل الرقم:", cid, c.message.message_id,
                reply_markup=make_inline_buttons(("✅ تأكيد", "mtn_unit_final_confirm"), ("❌ إلغاء", "cancel_all"))
            )
        bot.answer_callback_query(c.id)

    @bot.callback_query_handler(func=lambda c: c.data == "syr_unit_final_confirm")
    def syr_unit_final_confirm(c):
        uid = c.from_user.id
        unit = user_states[uid]["unit"]
        summary = (
            f"🔴 طلب وحدات سيرياتيل:\n"
            f"👤 المستخدم: {uid}\n"
            f"💵 الكمية: {unit['name']}\n"
            f"💰 السعر: {unit['price']:,} ل.س\n"
            f"✅ بانتظار موافقة الإدارة"
        )
        add_pending_request(uid, c.from_user.username, summary)
        bot.send_message(c.message.chat.id, "✅ تم إرسال الطلب للإدارة.")

    @bot.callback_query_handler(func=lambda c: c.data == "mtn_unit_final_confirm")
    def mtn_unit_final_confirm(c):
        uid = c.from_user.id
        unit = user_states[uid]["unit"]
        summary = (
            f"🟡 طلب وحدات MTN:\n"
            f"👤 المستخدم: {uid}\n"
            f"💵 الكمية: {unit['name']}\n"
            f"💰 السعر: {unit['price']:,} ل.س\n"
            f"✅ بانتظار موافقة الإدارة"
        )
        add_pending_request(uid, c.from_user.username, summary)
        bot.send_message(c.message.chat.id, "✅ تم إرسال الطلب للإدارة.")

    @bot.callback_query_handler(func=lambda c: c.data == "final_confirm_syr_bill")
    def final_confirm_syr_bill(c):
        uid = c.from_user.id
        amt = user_states[uid].get('amount', 0)
        fee = user_states[uid].get('fee', 0)
        total = amt + fee
        balance = get_balance(uid)
        if balance < total:
            bot.send_message(
                c.message.chat.id,
                f"❌ لا يوجد لديك رصيد كافٍ.\n"
                f"رصيدك الحالي: {balance:,} ل.س\n"
                f"المطلوب:       {total:,} ل.س"
            )
            return
        summary = (
            f"🔴 طلب دفع فاتورة سيرياتيل:\n"
            f"👤 المستخدم: {uid}\n"
            f"💵 المبلغ: {amt:,} ل.س\n"
            f"🧾 عمولة: {fee:,} ل.س"
        )
        add_pending_request(uid, c.from_user.username, summary)
        bot.send_message(c.message.chat.id, "✅ تم إرسال الطلب للإدارة.")

    @bot.callback_query_handler(func=lambda c: c.data == "final_confirm_mtn_bill")
    def final_confirm_mtn_bill(c):
        uid = c.from_user.id
        amt = user_states[uid].get('amount', 0)
        fee = user_states[uid].get('fee', 0)
        total = amt + fee
        balance = get_balance(uid)
        if balance < total:
            bot.send_message(
                c.message.chat.id,
                f"❌ لا يوجد لديك رصيد كافٍ.\n"
                f"رصيدك الحالي: {balance:,} ل.س\n"
                f"المطلوب:       {total:,} ل.س"
            )
            return
        summary = (
            f"🟡 طلب دفع فاتورة MTN:\n"
            f"👤 المستخدم: {uid}\n"
            f"💵 المبلغ: {amt:,} ل.س\n"
            f"🧾 عمولة: {fee:,} ل.س"
        )
        add_pending_request(uid, c.from_user.username, summary)
        bot.send_message(c.message.chat.id, "✅ تم إرسال الطلب للإدارة.")

    @bot.message_handler(func=lambda msg: msg.text and msg.text.startswith("/done_"))
    def handle_done(msg):
        rid = int(msg.text.split("_")[1])
        get_table("pending_requests").update({"status": "done"}).eq("id", rid).execute()
        bot.reply_to(msg, f"✅ تم إنهاء الطلب رقم {rid}")

    @bot.message_handler(func=lambda msg: msg.text and msg.text.startswith("/cancel_"))
    def handle_cancel(msg):
        rid = int(msg.text.split("_")[1])
        get_table("pending_requests").update({"status": "cancelled"}).eq("id", rid).execute()
        bot.reply_to(msg, f"🚫 تم إلغاء الطلب رقم {rid}")
