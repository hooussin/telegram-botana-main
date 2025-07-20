from telebot import types
import math
import logging
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

user_states = {}

# -------------------- أدوات مساعدة --------------------

def make_inline_buttons(*buttons):
    kb = types.InlineKeyboardMarkup()
    for text, data in buttons:
        kb.add(types.InlineKeyboardButton(text, callback_data=data))
    return kb


def _unit_label(unit: dict) -> str:
    return f"{unit['name']} - {unit['price']:,} ل.س"

# قوائم الردّ القديمة

def units_bills_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("🔴 وحدات سيرياتيل"),
        types.KeyboardButton("🔴 فاتورة سيرياتيل"),
        types.KeyboardButton("🟡 وحدات MTN"),
        types.KeyboardButton("🟡 فاتورة MTN"),
    )
    kb.add(types.KeyboardButton("⬅️ رجوع"))
    return kb

# قوائم إنلاين

def units_bills_menu_inline():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔴 وحدات سيرياتيل", callback_data="ubm:syr_units"))
    kb.add(types.InlineKeyboardButton("🔴 فاتورة سيرياتيل", callback_data="ubm:syr_bill"))
    kb.add(types.InlineKeyboardButton("🟡 وحدات MTN", callback_data="ubm:mtn_units"))
    kb.add(types.InlineKeyboardButton("🟡 فاتورة MTN", callback_data="ubm:mtn_bill"))
    kb.add(types.InlineKeyboardButton("⬅️ رجوع", callback_data="ubm:back"))
    return kb

# بناء كيبورد الصفحات

def _build_paged_inline_keyboard(items, page: int = 0, page_size: int = 5, prefix: str = "pg", back_data: str | None = None):
    total = len(items)
    pages = max(1, math.ceil(total / page_size))
    page = max(0, min(page, pages - 1))
    start = page * page_size
    end = start + page_size
    slice_items = items[start:end]

    kb = types.InlineKeyboardMarkup()
    for idx, label in slice_items:
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

# التسجيل الرئيسي

def register_bill_and_units(bot, history):
    """تسجيل خدمات وحدات وفواتير سيرياتيل وMTN"""

    # القائمة الرئيسية
    @bot.message_handler(func=lambda msg: msg.text == "💳 تحويل وحدات فاتورة سوري")
    def open_main_menu(msg):
        user_id = msg.from_user.id
        history.setdefault(user_id, []).append("units_bills_menu")
        user_states[user_id] = {"step": None}
        bot.send_message(msg.chat.id, "اختر الخدمة:", reply_markup=units_bills_menu_inline())

    # توجيه إنلاين
    @bot.callback_query_handler(func=lambda call: call.data.startswith("ubm:"))
    def ubm_router(call):
        action = call.data.split(":",1)[1]
        chat_id = call.message.chat.id
        user_id = call.from_user.id

        if action == "syr_units":
            user_states[user_id] = {"step": "select_syr_unit"}
            _send_syr_units_page(chat_id, 0, call.message.message_id)
        elif action == "syr_bill":
            user_states[user_id] = {"step": "syr_bill_number"}
            kb = make_inline_buttons(("❌ إلغاء","cancel_all"))
            bot.edit_message_text("📱 أدخل رقم سيرياتيل:\n", chat_id, call.message.message_id, reply_markup=kb)
        elif action == "mtn_units":
            user_states[user_id] = {"step": "select_mtn_unit"}
            _send_mtn_units_page(chat_id, 0, call.message.message_id)
        elif action == "mtn_bill":
            user_states[user_id] = {"step": "mtn_bill_number"}
            kb = make_inline_buttons(("❌ إلغاء","cancel_all"))
            bot.edit_message_text("📱 أدخل رقم MTN:\n", chat_id, call.message.message_id, reply_markup=kb)
        elif action == "back":
            from keyboards import main_menu as _main_menu
            bot.edit_message_text("⬅️ رجوع", chat_id, call.message.message_id)
            bot.send_message(chat_id, "اختر:", reply_markup=_main_menu())
        bot.answer_callback_query(call.id)

    # إرسال صفحات
    def _send_syr_units_page(chat_id, page, message_id=None):
        items = [(i,_unit_label(u)) for i,u in enumerate(SYRIATEL_UNITS)]
        kb,pages = _build_paged_inline_keyboard(items,page,5,"syrunits","ubm:back")
        text=f"اختر وحدات (صفحة {page+1}/{pages}):"
        if message_id:
            bot.edit_message_text(text,chat_id,message_id,reply_markup=kb)
        else:
            bot.send_message(chat_id,text,reply_markup=kb)

    def _send_mtn_units_page(chat_id, page, message_id=None):
        items = [(i,_unit_label(u)) for i,u in enumerate(MTN_UNITS)]
        kb,pages = _build_paged_inline_keyboard(items,page,5,"mtnunits","ubm:back")
        text=f"اختر وحدات MTN (صفحة {page+1}/{pages}):"
        if message_id:
            bot.edit_message_text(text,chat_id,message_id,reply_markup=kb)
        else:
            bot.send_message(chat_id,text,reply_markup=kb)

    # اختيار عبر إنلاين
    @bot.callback_query_handler(func=lambda call: call.data.startswith("syrunits:"))
    def syr_units_inline_handler(call):
        _,action,value=call.data.split(":")
        uid=call.from_user.id;cid=call.message.chat.id
        if action=="page": _send_syr_units_page(cid,int(value),call.message.message_id)
        elif action=="sel":
            unit=SYRIATEL_UNITS[int(value)]
            user_states[uid]={"step":"syr_unit_number","unit":unit}
            kb=make_inline_buttons(("❌ إلغاء","cancel_all"))
            bot.edit_message_text("📱 أدخل الرقم:",cid,call.message.message_id,reply_markup=kb)
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("mtnunits:"))
    def mtn_units_inline_handler(call):
        _,action,value=call.data.split(":")
        uid=call.from_user.id;cid=call.message.chat.id
        if action=="page": _send_mtn_units_page(cid,int(value),call.message.message_id)
        elif action=="sel":
            unit=MTN_UNITS[int(value)]
            user_states[uid]={"step":"mtn_unit_number","unit":unit}
            kb=make_inline_buttons(("❌ إلغاء","cancel_all"))
            bot.edit_message_text("📱 أدخل الرقم:",cid,call.message.message_id,reply_markup=kb)
        bot.answer_callback_query(call.id)

    # handlers للرسائل
    @bot.message_handler(func=lambda m: m.text=="🔴 وحدات سيرياتيل")
    def syr_units_menu(m):
        uid=m.from_user.id;kb=types.ReplyKeyboardMarkup(resize_keyboard=True,row_width=2)
        for u in SYRIATEL_UNITS: kb.add(types.KeyboardButton(_unit_label(u)))
        kb.add(types.KeyboardButton("⬅️ رجوع"));user_states[uid]={"step":"select_syr_unit"}
        bot.send_message(m.chat.id,"اختر:",reply_markup=kb)

    @bot.message_handler(func=lambda m:user_states.get(m.from_user.id,{}).get("step")=="select_syr_unit")
    def syr_unit_select(m):
        uid=m.from_user.id;unit=next((u for u in SYRIATEL_UNITS if _unit_label(u)==m.text),None)
        if not unit: return
        user_states[uid]={"step":"syr_unit_final","unit":unit}
        kb=make_inline_buttons(("✅ تأكيد","syr_unit_final_confirm"),("❌ إلغاء","cancel_all"))
        bot.send_message(m.chat.id,f"تأكيد طلب {unit['name']}؟",reply_markup=kb)

    # final confirm handlers
    @bot.callback_query_handler(func=lambda c:c.data=="syr_unit_final_confirm")
    def syr_unit_final_confirm(call):
        uid=call.from_user.id;st=user_states[uid]
        summary=f"🔴 طلب وحدات سيرياتيل:\n👤 {uid}\nوحدة {st['unit']['name']}\n"
        add_pending_request(uid,call.from_user.username,summary)
        bot.send_message(call.message.chat.id,"✅ تم إرسال للإدارة.")

    @bot.callback_query_handler(func=lambda c:c.data=="mtn_unit_final_confirm")
    def mtn_unit_final_confirm(call):
        uid=call.from_user.id;st=user_states[uid]
        summary=f"🟡 طلب وحدات MTN:\n👤 {uid}\nوحدة {st['unit']['name']}\n"
        add_pending_request(uid,call.from_user.username,summary)
        bot.send_message(call.message.chat.id,"✅ تم إرسال للإدارة.")

    @bot.callback_query_handler(func=lambda c:c.data=="final_confirm_syr_bill")
    def final_confirm_syr_bill(call):
        uid=call.from_user.id;bal=get_balance(uid);amt=user_states[uid].get('amount',0)
        fee=user_states[uid].get('fee',0);total=amt+fee
        if bal<total: return
        summary=f"🔴 فاتورة سيرياتيل:\n👤 {uid}\nمبلغ {amt}\nعمولة {fee}\n"
        add_pending_request(uid,call.from_user.username,summary)
        bot.send_message(call.message.chat.id,"✅ تم إرسال.")

    @bot.callback_query_handler(func=lambda c:c.data=="final_confirm_mtn_bill")
    def final_confirm_mtn_bill(call):
        uid=call.from_user.id;bal=get_balance(uid);amt=user_states[uid].get('amount',0)
        fee=user_states[uid].get('fee',0);total=amt+fee
        if bal<total: return
        summary=f"🟡 فاتورة MTN:\n👤 {uid}\nمبلغ {amt}\nعمولة {fee}\n"
        add_pending_request(uid,call.from_user.username,summary)
        bot.send_message(call.message.chat.id,"✅ تم إرسال.")

    # handlers للالغاء والانتهاء من الادمن
    @bot.message_handler(func=lambda m:m.text and m.text.startswith("/done_"))
    def handle_done(m):
        rid=int(m.text.split("_")[1]);
        get_table("pending_requests").update({"status":"done"}).eq("id",rid).execute()
        bot.reply_to(m,f"✅ تم إنهاء {rid}")

    @bot.message_handler(func=lambda m:m.text and m.text.startswith("/cancel_"))
    def handle_cancel(m):
        rid=int(m.text.split("_")[1]);
        get_table("pending_requests").update({"status":"cancelled"}).eq("id",rid).execute()
        bot.reply_to(m,f"🚫 تم إلغاء {rid}")

    # احتفظ بكل الأوامر الأخرى كما كانت دون حذف
