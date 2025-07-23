from telebot import types
import math  # added for pagination support
import logging
import re  # for phone validation

from services.wallet_service import (
    get_balance,
    deduct_balance,
    add_balance,
    register_user_if_not_exist,
    add_purchase,
    has_sufficient_balance,
    _update_balance,
)
from config import ADMIN_MAIN_ID
from services.queue_service import add_pending_request, process_queue

# --- قوائم المنتجات (وحدات) وأسعارها (لم يتم تعديل القيم) ---
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

pending_users = set()  # track users with pending requests

# -------------------- أدوات مساعدة عامة --------------------

def make_inline_buttons(*buttons):
    kb = types.InlineKeyboardMarkup()
    for text, data in buttons:
        kb.add(types.InlineKeyboardButton(text, callback_data=data))
    return kb

def _unit_label(unit: dict) -> str:
    return f"{unit['name']} - {unit['price']:,} ل.س"

# لوحة Reply القديمة (للخلفية/التوافق)
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

# النسخة الجديدة: InlineKeyboard أساسي
def units_bills_menu_inline():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔴 وحدات سيرياتيل", callback_data="ubm:syr_units"))
    kb.add(types.InlineKeyboardButton("🔴 فاتورة سيرياتيل", callback_data="ubm:syr_bill"))
    kb.add(types.InlineKeyboardButton("🟡 وحدات MTN", callback_data="ubm:mtn_units"))
    kb.add(types.InlineKeyboardButton("🟡 فاتورة MTN", callback_data="ubm:mtn_bill"))
    kb.add(types.InlineKeyboardButton("⬅️ رجوع", callback_data="ubm:back"))
    return kb

# باني كيبورد صفحات عام
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

    # navigation row
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

# =======================================================================
# التسجيل الرئيسي
# =======================================================================
def register_bill_and_units(bot, history):
    """تسجيل جميع هاندلرات خدمات (وحدات/فواتير) لكل من سيرياتيل و MTN.
    تم إضافة دعم InlineKeyboard مع Pagination دون المساس بمنطق المراحل الحالي.
    كل الهاندلرات الأصلية (القائمة على ReplyKeyboard) باقية كما هي للتوافق.
    """

    # ===== القائمة الرئيسية للخدمة =====
    @bot.message_handler(func=lambda msg: msg.text == "💳 تحويل وحدات فاتورة سوري")
    def open_main_menu(msg):
        user_id = msg.from_user.id
        history.setdefault(user_id, []).append("units_bills_menu")
        user_states[user_id] = {"step": None}
        # تم استبدال لوحة الرد بلوحة إنلاين
        bot.send_message(msg.chat.id, "اختر الخدمة:", reply_markup=units_bills_menu_inline())

    # --------- Router له واجهة الإنلاين الرئيسية ---------
    @bot.callback_query_handler(func=lambda call: call.data.startswith("ubm:")) 
    def ubm_router(call):
        action = call.data.split(":", 1)[1]
        chat_id = call.message.chat.id
        user_id = call.from_user.id

        if action == "syr_units":
            # نفس منطق syr_units_menu (تحديد مرحلة وفتح قائمة الوحدات)
            user_states[user_id] = {"step": "select_syr_unit"}
            _send_syr_units_page(chat_id, page=0, message_id=call.message.message_id)
            bot.answer_callback_query(call.id)
            return

        if action == "syr_bill":
            # إعادة استعمال منطق syr_bill_entry
            user_states[user_id] = {"step": "syr_bill_number"}
            kb = make_inline_buttons(("❌ إلغاء", "cancel_all"))
            bot.edit_message_text("📱 أدخل رقم سيرياتيل المراد دفع فاتورته:", chat_id, call.message.message_id, reply_markup=kb)
            bot.answer_callback_query(call.id)
            return

        if action == "mtn_units":
            user_states[user_id] = {"step": "select_mtn_unit"}
            _send_mtn_units_page(chat_id, page=0, message_id=call.message.message_id)
            bot.answer_callback_query(call.id)
            return

        if action == "mtn_bill":
            user_states[user_id] = {"step": "mtn_bill_number"}
            kb = make_inline_buttons(("❌ إلغاء", "cancel_all"))
            bot.edit_message_text("📱 أدخل رقم MTN المراد دفع فاتورته:", chat_id, call.message.message_id, reply_markup=kb)
            bot.answer_callback_query(call.id)
            return

        if action == "back":
            # رجوع إلى القائمة الرئيسية للبوت (Reply القديمة) دون تعديل المنطق العام
            try:
                from keyboards import main_menu as _main_menu
                bot.edit_message_text("⬅️ رجوع", chat_id, call.message.message_id)
                bot.send_message(chat_id, "اختر من القائمة:", reply_markup=_main_menu())
            except Exception:
                bot.edit_message_text("⬅️ رجوع", chat_id, call.message.message_id)
            bot.answer_callback_query(call.id)
            return

        bot.answer_callback_query(call.id)

    # ---------- أدوات إرسال قوائم الوحدات (Inline + Pagination) ----------
    PAGE_SIZE_UNITS = 5

    def _send_syr_units_page(chat_id, page=0, message_id=None):
        items = [(idx, _unit_label(u)) for idx, u in enumerate(SYRIATEL_UNITS)]
        kb, pages = _build_paged_inline_keyboard(items, page=page, page_size=PAGE_SIZE_UNITS, prefix="syrunits", back_data="ubm:back")
        text = f"اختر كمية الوحدات (صفحة {page+1}/{pages}):"
        if message_id is not None:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=kb)
        else:
            bot.send_message(chat_id, text, reply_markup=kb)

    def _send_mtn_units_page(chat_id, page=0, message_id=None):
        items = [(idx, _unit_label(u)) for idx, u in enumerate(MTN_UNITS)]
        kb, pages = _build_paged_inline_keyboard(items, page=page, page_size=PAGE_SIZE_UNITS, prefix="mtnunits", back_data="ubm:back")
        text = f"اختر كمية الوحدات (صفحة {page+1}/{pages}):"
        if message_id is not None:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=kb)
        else:
            bot.send_message(chat_id, text, reply_markup=kb)

    # ------ ملاحق كولباك للوحدات (سيرياتيل) ------
    @bot.callback_query_handler(func=lambda call: call.data.startswith("syrunits:"))
    def syr_units_inline_handler(call):
        parts = call.data.split(":")
        action = parts[1]
        chat_id = call.message.chat.id
        user_id = call.from_user.id

        if action == "page":
            page = int(parts[2]) if len(parts)>2 else 0
            _send_syr_units_page(chat_id, page=page, message_id=call.message.message_id)
            bot.answer_callback_query(call.id)
            return

        if action == "sel":
            idx = int(parts[2])
            unit = SYRIATEL_UNITS[idx]
            user_states[user_id] = {"step": "syr_unit_number", "unit": unit}
            kb = make_inline_buttons(("❌ إلغاء", "cancel_all"))
            bot.edit_message_text("📱 أدخل الرقم أو الكود الذي يبدأ بـ 093 أو 098 أو 099:", chat_id, call.message.message_id, reply_markup=kb)
            bot.answer_callback_query(call.id, text=_unit_label(unit))
            return

        if action == "back":
            bot.edit_message_text("اختر الخدمة:", chat_id, call.message.message_id, reply_markup=units_bills_menu_inline())
            bot.answer_callback_query(call.id)
            return

        bot.answer_callback_query(call.id)

    # ------ ملاحق كولباك للوحدات (MTN) ------
    @bot.callback_query_handler(func=lambda call: call.data.startswith("mtnunits:"))
    def mtn_units_inline_handler(call):
        parts = call.data.split(":")
        action = parts[1]
        chat_id = call.message.chat.id
        user_id = call.from_user.id

        if action == "page":
            page = int(parts[2]) if len(parts)>2 else 0
            _send_mtn_units_page(chat_id, page=page, message_id=call.message.message_id)
            bot.answer_callback_query(call.id)
            return

        if action == "sel":
            idx = int(parts[2])
            unit = MTN_UNITS[idx]
            user_states[user_id] = {"step": "mtn_unit_number", "unit": unit}
            kb = make_inline_buttons(("❌ إلغاء", "cancel_all"))
            bot.edit_message_text("📱 أدخل الرقم أو الكود الذي يبدأ بـ 094 أو 095 أو 096:", chat_id, call.message.message_id, reply_markup=kb)
            bot.answer_callback_query(call.id, text=_unit_label(unit))
            return

        if action == "back":
            bot.edit_message_text("اختر الخدمة:", chat_id, call.message.message_id, reply_markup=units_bills_menu_inline())
            bot.answer_callback_query(call.id)
            return

        bot.answer_callback_query(call.id)

    # ===================================================================
    # أدناه الكود الأصلي للمعالجة بالرسائل (ReplyKeyboard) بدون أي تعديل
    # ===================================================================
          ########## وحدات سيرياتيل ##########
    @bot.message_handler(func=lambda m: m.text == "🔴 وحدات سيرياتيل")
    def syr_units_menu(msg):
        uid = msg.from_user.id
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        for u in SYRIATEL_UNITS:
            kb.add(types.KeyboardButton(_unit_label(u)))
        kb.add(types.KeyboardButton("⬅️ رجوع"))
        user_states[uid] = {"step": "select_syr_unit"}
        bot.send_message(msg.chat.id, "اختر كمية الوحدات:", reply_markup=kb)

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("step") == "select_syr_unit")
    def syr_unit_select(msg):
        uid = msg.from_user.id
        unit = next((u for u in SYRIATEL_UNITS if _unit_label(u) == msg.text), None)
        if not unit:
            return bot.send_message(msg.chat.id, "⚠️ اختر كمية من القائمة.")
        user_states[uid] = {"step": "syr_unit_number", "unit": unit}
        kb = make_inline_buttons(("❌ إلغاء", "cancel_all"))
        bot.send_message(msg.chat.id, "📱 أدخل الرقم الذي يبدأ بـ 09 ومؤلف من 10 أرقام:", reply_markup=kb)

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("step") == "syr_unit_number")
    def syr_unit_number(msg):
        uid = msg.from_user.id
        number = msg.text.strip()
        if not re.match(r"^09\d{8}$", number):
            return bot.send_message(msg.chat.id, "⚠️ الرقم غير صالح، تأكد أنه يبدأ بـ 09 ومؤلف من 10 أرقام.")
        st = user_states[uid]
        st["number"] = number
        st["step"] = "syr_unit_confirm"
        unit = st["unit"]
        kb = make_inline_buttons(
            ("❌ إلغاء", "cancel_all"),
            ("✔️ تأكيد الشراء", "syr_unit_final_confirm")
        )
        bot.send_message(
            msg.chat.id,
            f"هل أنت متأكد من شراء {unit['name']} بسعر {unit['price']:,} ل.س للرقم:\n{number}؟",
            reply_markup=kb
        )

    @bot.callback_query_handler(func=lambda c: c.data == "syr_unit_final_confirm")
    def syr_unit_final_confirm(call):
        uid = call.from_user.id

        # منع تعدّد الطلبات
        if uid in pending_users:
            bot.answer_callback_query(call.id, "🔥 لديك طلب قيد الانتظار بالفعل")
            return

        st = user_states.get(uid, {})
        price = st["unit"]["price"]
        balance = get_balance(uid)
        if balance < price:
            kb = make_inline_buttons(("❌ إلغاء", "cancel_all"), ("💼 المحفظة", "go_wallet"))
            bot.send_message(
                uid,
                f"❌ لا يوجد رصيد كافٍ.\nرصيدك: {balance:,} ل.س\nالمطلوب: {price:,} ل.س",
                reply_markup=kb
            )
            bot.answer_callback_query(call.id, "❌ رصيد غير كافٍ")
            user_states.pop(uid, None)
            return

        # إضافة إلى الطابور
        pending_users.add(uid)
        st["step"] = "wait_admin_syr_unit"
        add_pending_request(
            user_id=uid,
            username=call.from_user.username,
            request_text=(
                f"🔴 وحدات سيرياتيل:\n"
                f"👤 المستخدم: <code>{uid}</code>\n"
                f"📱 <code>{st['number']}</code>\n"
                f"💵 {st['unit']['name']}\n"
                f"💰 {price:,} ل.س"
            )
        )
        process_queue(bot)
        bot.answer_callback_query(call.id, "✅ تم إرسال الطلب للإدارة")
        bot.send_message(call.message.chat.id, "✅ تم إرسال طلبك للإدارة، بانتظار الموافقة.")

    # ------ موافقة/رفض الإدارة (يجب أن تكون بمستوى 4 مسافات، خارج الدالة السابقة) ------
    
    @bot.callback_query_handler(func=lambda c: c.data.startswith("admin_accept_syr_unit_"))
    def admin_accept_syr_unit(call):
        uid = int(call.data.split("_")[-1])
        st = user_states.get(uid, {})
        number = st.get("number", "")
        unit_name = st.get("unit", {}).get("name", "")
        # سطور الطباعة المهمة!
        print("==== DEBUG admin_accept_syr_unit ====")
        print("user_states[uid]:", st)
        print("unit_name:", repr(unit_name))
        print("SYRIATEL_UNITS:", [u["name"] for u in SYRIATEL_UNITS])
        # احصل على السعر من القائمة الأصلية
        price = next((u["price"] for u in SYRIATEL_UNITS if u["name"] == unit_name), 0)

        if not has_sufficient_balance(uid, price):
            bal = get_balance(uid)
            bot.send_message(uid, f"❌ لا يوجد رصيد كافٍ.\nرصيدك: {bal:,} ل.س\nالمطلوب: {price:,} ل.س")
            return bot.answer_callback_query(call.id, "❌")

        pending_users.discard(uid)
        _update_balance(uid, -price)
        add_purchase(uid, 0, unit_name, price, number)
        bot.send_message(
            uid,
            f"✅ تم تحويل {unit_name} إلى الرقم <code>{number}</code>\n"
            f"وتم خصم {price:,} ل.س من محفظتك.",
            parse_mode="HTML"
        )
        bot.answer_callback_query(call.id, "✅")
        user_states.pop(uid, None)


    @bot.callback_query_handler(func=lambda c: c.data.startswith("admin_reject_syr_unit_"))
    def admin_reject_syr_unit(call):
        uid = int(call.data.split("_")[-1])
        pending_users.discard(uid)
        bot.send_message(uid, "❌ تم رفض طلب وحدات سيرياتيل من الإدارة.")
        bot.answer_callback_query(call.id, "❌ تم رفض الطلب")
        user_states.pop(uid, None)

    ########## وحدات MTN ##########
    @bot.message_handler(func=lambda m: m.text == "🟡 وحدات MTN")
    def mtn_units_menu(msg):
        uid = msg.from_user.id
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        for u in MTN_UNITS:
            kb.add(types.KeyboardButton(_unit_label(u)))
        kb.add(types.KeyboardButton("⬅️ رجوع"))
        user_states[uid] = {"step": "select_mtn_unit"}
        bot.send_message(msg.chat.id, "اختر كمية الوحدات:", reply_markup=kb)

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("step") == "select_mtn_unit")
    def mtn_unit_select(msg):
        uid = msg.from_user.id
        unit = next((u for u in MTN_UNITS if _unit_label(u) == msg.text), None)
        if not unit:
            return bot.send_message(msg.chat.id, "⚠️ اختر كمية من القائمة.")
        user_states[uid] = {"step": "mtn_unit_number", "unit": unit}
        kb = make_inline_buttons(("❌ إلغاء", "cancel_all"))
        bot.send_message(msg.chat.id, "📱 أدخل الرقم الذي يبدأ بـ 09 ومؤلف من 10 أرقام:", reply_markup=kb)

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("step") == "mtn_unit_number")
    def mtn_unit_number(msg):
        uid = msg.from_user.id
        number = msg.text.strip()
        if not re.match(r"^09\d{8}$", number):
            return bot.send_message(msg.chat.id, "⚠️ الرقم غير صالح، تأكد أنه يبدأ بـ 09 ومؤلف من 10 أرقام.")
        st = user_states[uid]
        st["number"] = number
        st["step"] = "mtn_unit_confirm"
        unit = st["unit"]
        kb = make_inline_buttons(
            ("❌ إلغاء", "cancel_all"),
            ("✔️ تأكيد الشراء", "mtn_unit_final_confirm")
        )
        bot.send_message(
            msg.chat.id,
            f"هل أنت متأكد من شراء {unit['name']} بسعر {unit['price']:,} ل.س للرقم:\n{number}؟",
            reply_markup=kb
        )

    @bot.callback_query_handler(func=lambda c: c.data == "mtn_unit_final_confirm")
    def mtn_unit_final_confirm(call):
        uid = call.from_user.id

        # منع طلب مكرّر
        if uid in pending_users:
            bot.answer_callback_query(call.id, "🔥 لديك طلب قيد الانتظار بالفعل")
            return

        st = user_states.get(uid, {})
        price = st["unit"]["price"]
        balance = get_balance(uid)
        if balance < price:
            kb = make_inline_buttons(("❌ إلغاء", "cancel_all"), ("💼 المحفظة", "go_wallet"))
            bot.send_message(
                uid,
                f"❌ لا يوجد رصيد كافٍ.\nرصيدك: {balance:,} ل.س\nالمطلوب: {price:,} ل.س",
                reply_markup=kb
            )
            bot.answer_callback_query(call.id, "❌ رصيد غير كافٍ")
            user_states.pop(uid, None)
            return

        # إضافة للطابور
        pending_users.add(uid)
        st["step"] = "wait_admin_mtn_unit"
        add_pending_request(
            user_id=uid,
            username=call.from_user.username,
            request_text=(
                f"🟡 وحدات MTN:\n"
                f"👤 المستخدم: <code>{uid}</code>\n"
                f"📱 <code>{st['number']}</code>\n"
                f"💵 {st['unit']['name']}\n"
                f"💰 {price:,} ل.س"
            )
        )
        process_queue(bot)
        bot.answer_callback_query(call.id, "✅ تم إرسال الطلب للإدارة")
        bot.send_message(call.message.chat.id, "✅ تم إرسال طلبك للإدارة، بانتظار الموافقة.")

    # ------ موافقة/رفض الإدارة ------

    @bot.callback_query_handler(func=lambda c: c.data.startswith("admin_accept_mtn_unit_"))
    def admin_accept_mtn_unit(call):
        uid = int(call.data.split("_")[-1])
        st = user_states.get(uid, {})
        number = st.get("number", "")
        unit_name = st.get("unit", {}).get("name", "")
        # جلب السعر الصحيح من القائمة MTN_UNITS
        price = next((u["price"] for u in MTN_UNITS if u["name"] == unit_name), 0)

        if not has_sufficient_balance(uid, price):
            bal = get_balance(uid)
            bot.send_message(uid, f"❌ رصيدك {bal:,} ل.س والمطلوب {price:,} ل.س.")
            return bot.answer_callback_query(call.id, "❌")

        pending_users.discard(uid)
        _update_balance(uid, -price)
        add_purchase(uid, 0, unit_name, price, number)
        bot.send_message(
            uid,
            f"✅ تم تحويل {unit_name} إلى الرقم <code>{number}</code>\n"
            f"وتم خصم {price:,} ل.س من محفظتك.",
            parse_mode="HTML"
        )
        bot.answer_callback_query(call.id, "✅")
        user_states.pop(uid, None)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("admin_reject_mtn_unit_"))
    def admin_reject_mtn_unit(call):
        uid = int(call.data.split("_")[-1])
        pending_users.discard(uid)
        bot.send_message(uid, "❌ تم رفض طلب وحدات MTN من الإدارة.")
        bot.answer_callback_query(call.id, "❌ تم رفض الطلب")
        user_states.pop(uid, None)

    ########## فاتورة سيرياتيل ##########

    @bot.message_handler(func=lambda m: m.text == "🔴 فاتورة سيرياتيل")
    def syr_bill_entry(msg):
        uid = msg.from_user.id
        user_states[uid] = {"step": "syr_bill_number"}
        kb = make_inline_buttons(("❌ إلغاء", "cancel_all"))
        bot.send_message(msg.chat.id, "📱 أدخل رقم سيرياتيل المراد دفع فاتورته:", reply_markup=kb)

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("step") == "syr_bill_number")
    def syr_bill_number(msg):
        uid = msg.from_user.id
        number = msg.text.strip()
        if not re.match(r"^09\d{8}$", number):
            return bot.send_message(msg.chat.id, "⚠️ الرقم غير صالح، تأكد أنه يبدأ بـ 09 ومؤلف من 10 أرقام.")
        st = user_states[uid]
        st["number"] = number
        st["step"] = "syr_bill_number_confirm"
        kb = make_inline_buttons(
            ("❌ إلغاء", "cancel_all"),
            ("✏️ تعديل", "edit_syr_bill_number"),
            ("✔️ تأكيد", "confirm_syr_bill_number")
        )
        bot.send_message(msg.chat.id, f"هل الرقم التالي صحيح؟\n{number}", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data == "edit_syr_bill_number")
    def edit_syr_bill_number(call):
        uid = call.from_user.id
        user_states[uid]["step"] = "syr_bill_number"
        bot.send_message(call.message.chat.id, "📱 أعد إدخال رقم الموبايل:")

    @bot.callback_query_handler(func=lambda c: c.data == "confirm_syr_bill_number")
    def confirm_syr_bill_number(call):
        uid = call.from_user.id
        user_states[uid]["step"] = "syr_bill_amount"
        kb = make_inline_buttons(("❌ إلغاء", "cancel_all"))
        bot.send_message(call.message.chat.id, "💵 أدخل مبلغ الفاتورة بالليرة:", reply_markup=kb)

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("step") == "syr_bill_amount")
    def syr_bill_amount(msg):
        uid = msg.from_user.id
        try:
            amount = int(msg.text)
            if amount <= 0:
                raise ValueError
        except ValueError:
            return bot.send_message(msg.chat.id, "⚠️ أدخل مبلغ صحيح.")
        st = user_states[uid]
        st["amount"] = amount
        st["step"] = "syr_bill_amount_confirm"
        kb = make_inline_buttons(
            ("❌ إلغاء", "cancel_all"),
            ("✏️ تعديل", "edit_syr_bill_amount"),
            ("✔️ تأكيد", "confirm_syr_bill_amount")
        )
        bot.send_message(
            msg.chat.id,
            f"هل المبلغ التالي صحيح؟\n{amount:,} ل.س",
            reply_markup=kb
        )

    @bot.callback_query_handler(func=lambda c: c.data == "edit_syr_bill_amount")
    def edit_syr_bill_amount(call):
        uid = call.from_user.id
        user_states[uid]["step"] = "syr_bill_amount"
        bot.send_message(call.message.chat.id, "💵 أعد إرسال مبلغ الفاتورة:")

    @bot.callback_query_handler(func=lambda c: c.data == "confirm_syr_bill_amount")
    def confirm_syr_bill_amount(call):
        uid = call.from_user.id
        st = user_states[uid]
        amount = st["amount"]
        total = int(amount * 1.17)
        st["amount_with_fee"] = total
        st["step"] = "syr_bill_final_confirm"
        kb = make_inline_buttons(
            ("❌ إلغاء", "cancel_all"),
            ("✔️ تأكيد", "final_confirm_syr_bill")
        )
        bot.send_message(
            call.message.chat.id,
            f"سيتم دفع فاتورة سيرياتيل للرقم: {st['number']}\n"
            f"المبلغ: {amount:,} ل.س\n"
            f"أجور التحويل : {total-amount:,} ل.س\n"
            f"الإجمالي: {total:,} ل.س\n"
            "هل تريد المتابعة؟",
            reply_markup=kb
        )

    @bot.callback_query_handler(func=lambda c: c.data == "final_confirm_syr_bill")
    def final_confirm_syr_bill(call):
        uid = call.from_user.id

        # منع تكرار الطلبات
        if uid in pending_users:
            bot.answer_callback_query(call.id, "🔥 لديك طلب قيد الانتظار بالفعل")
            return

        st = user_states.get(uid, {})
        total = st.get("amount_with_fee", 0)
        balance = get_balance(uid)
        if balance < total:
            kb = make_inline_buttons(("❌ إلغاء", "cancel_all"), ("💼 المحفظة", "go_wallet"))
            bot.send_message(
                uid,
                f"❌ رصيدك {balance:,} ل.س والمطلوب {total:,} ل.س.",
                reply_markup=kb
            )
            bot.answer_callback_query(call.id, "❌")
            user_states.pop(uid, None)
            return

        pending_users.add(uid)
        st["step"] = "wait_admin_syr_bill"
        add_pending_request(
            user_id=uid,
            username=call.from_user.username,
            request_text=(
                f"🔴 فاتورة سيرياتيل:\n"
                f"👤 المستخدم: <code>{uid}</code>\n"
                f"📱 <code>{st['number']}</code>\n"
                f"💵 {st['amount']:,} ل.س\n"
                f"🧾 مع العمولة : {total:,} ل.س"
            )
        )
        process_queue(bot)
        bot.answer_callback_query(call.id, "✅ تم إرسال الطلب للإدارة")
        bot.send_message(call.message.chat.id, "✅ تم إرسال طلب الفاتورة للإدارة، بانتظار الموافقة.")

# ------ موافقة/رفض الإدارة ------

    @bot.callback_query_handler(func=lambda c: c.data.startswith("admin_accept_syr_bill_"))
    def admin_accept_syr_bill(call):
        uid = int(call.data.split("_")[-1])
        st = user_states.get(uid, {})
        total = st.get("amount_with_fee", 0)
        number = st.get("number", "")
        amount = st.get("amount", 0)

        if not has_sufficient_balance(uid, total):
            bal = get_balance(uid)
            bot.send_message(uid, f"❌ رصيدك {bal:,} ل.س والمطلوب {total:,} ل.س.")
            return bot.answer_callback_query(call.id, "❌")

        pending_users.discard(uid)
        _update_balance(uid, -total)
        add_purchase(uid, 0, "فاتورة سيرياتيل", total, number)
        bot.send_message(
            uid,
            f"✅ تم دفع فاتورة الرقم <code>{number}</code>\n"
            f"بمبلغ {amount:,} ل.س وخصم إجمالي {total:,} ل.س من محفظتك.",
            parse_mode="HTML"
        )
        bot.answer_callback_query(call.id, "✅")
        user_states.pop(uid, None)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("admin_reject_syr_bill_"))
    def admin_reject_syr_bill(call):
        uid = int(call.data.split("_")[-1])
        pending_users.discard(uid)
        bot.send_message(uid, "❌ تم رفض طلب دفع الفاتورة من الإدارة.")
        bot.answer_callback_query(call.id, "❌ تم رفض الطلب")
        user_states.pop(uid, None)
    
    ########## فاتورة MTN ##########
    @bot.message_handler(func=lambda m: m.text == "🟡 فاتورة MTN")
    def mtn_bill_entry(msg):
        uid = msg.from_user.id
        user_states[uid] = {"step": "mtn_bill_number"}
        kb = make_inline_buttons(("❌ إلغاء", "cancel_all"))
        bot.send_message(msg.chat.id, "📱 أدخل رقم MTN المراد دفع فاتورته:", reply_markup=kb)

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("step") == "mtn_bill_number")
    def mtn_bill_number(msg):
        uid = msg.from_user.id
        number = msg.text.strip()
        if not re.match(r"^09\d{8}$", number):
            return bot.send_message(msg.chat.id, "⚠️ الرقم غير صالح، تأكد أنه يبدأ بـ 09 ومؤلف من 10 أرقام.")
        st = user_states[uid]
        st["number"] = number
        st["step"] = "mtn_bill_number_confirm"
        kb = make_inline_buttons(
            ("❌ إلغاء", "cancel_all"),
            ("✏️ تعديل", "edit_mtn_bill_number"),
            ("✔️ تأكيد", "confirm_mtn_bill_number")
        )
        bot.send_message(msg.chat.id, f"هل الرقم التالي صحيح؟\n{number}", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data == "edit_mtn_bill_number")
    def edit_mtn_bill_number(call):
        uid = call.from_user.id
        user_states[uid]["step"] = "mtn_bill_number"
        bot.send_message(call.message.chat.id, "📱 أعد إدخال رقم الموبايل:")

    @bot.callback_query_handler(func=lambda c: c.data == "confirm_mtn_bill_number")
    def confirm_mtn_bill_number(call):
        uid = call.from_user.id
        user_states[uid]["step"] = "mtn_bill_amount"
        kb = make_inline_buttons(("❌ إلغاء", "cancel_all"))
        bot.send_message(call.message.chat.id, "💵 أدخل مبلغ الفاتورة بالليرة:", reply_markup=kb)

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("step") == "mtn_bill_amount")
    def mtn_bill_amount(msg):
        uid = msg.from_user.id
        try:
            amount = int(msg.text)
            if amount <= 0:
                raise ValueError
        except ValueError:
            return bot.send_message(msg.chat.id, "⚠️ أدخل مبلغ صحيح.")
        st = user_states[uid]
        st["amount"] = amount
        st["step"] = "mtn_bill_amount_confirm"
        kb = make_inline_buttons(
            ("❌ إلغاء", "cancel_all"),
            ("✏️ تعديل", "edit_mtn_bill_amount"),
            ("✔️ تأكيد", "confirm_mtn_bill_amount")
        )
        bot.send_message(
            msg.chat.id,
            f"هل المبلغ التالي صحيح؟\n{amount:,} ل.س",
            reply_markup=kb
        )

    @bot.callback_query_handler(func=lambda c: c.data == "edit_mtn_bill_amount")
    def edit_mtn_bill_amount(call):
        uid = call.from_user.id
        user_states[uid]["step"] = "mtn_bill_amount"
        bot.send_message(call.message.chat.id, "💵 أعد إرسال مبلغ الفاتورة:")

    @bot.callback_query_handler(func=lambda c: c.data == "confirm_mtn_bill_amount")
    def confirm_mtn_bill_amount(call):
        uid = call.from_user.id
        st = user_states[uid]
        amount = st["amount"]
        total = int(amount * 1.17)
        st["amount_with_fee"] = total
        st["step"] = "mtn_bill_final_confirm"
        kb = make_inline_buttons(
            ("❌ إلغاء", "cancel_all"),
            ("✔️ تأكيد", "final_confirm_mtn_bill")
        )
        bot.send_message(
            call.message.chat.id,
            f"سيتم دفع فاتورة MTN للرقم: {st['number']}\n"
            f"المبلغ: {amount:,} ل.س\n"
            f"أجور التحويل : {total-amount:,} ل.س\n"
            f"الإجمالي: {total:,} ل.س\n"
            "هل تريد المتابعة؟",
            reply_markup=kb
        )

    @bot.callback_query_handler(func=lambda c: c.data == "final_confirm_mtn_bill")
    def final_confirm_mtn_bill(call):
        uid = call.from_user.id

        if uid in pending_users:
            bot.answer_callback_query(call.id, "🔥 لديك طلب قيد الانتظار بالفعل")
            return

        st = user_states.get(uid, {})
        total = st.get("amount_with_fee", 0)
        balance = get_balance(uid)
        if balance < total:
            kb = make_inline_buttons(("❌ إلغاء", "cancel_all"), ("💼 المحفظة", "go_wallet"))
            bot.send_message(
                uid,
                f"❌ رصيدك {balance:,} ل.س والمطلوب {total:,} ل.س.",
                reply_markup=kb
            )
            bot.answer_callback_query(call.id, "❌")
            user_states.pop(uid, None)
            return

        pending_users.add(uid)
        st["step"] = "wait_admin_mtn_bill"
        add_pending_request(
            user_id=uid,
            username=call.from_user.username,
            request_text=(
                f"🟡 فاتورة MTN:\n"
                f"👤 المستخدم: <code>{uid}</code>\n"
                f"📱 <code>{st['number']}</code>\n"
                f"💵 {st['amount']:,} ل.س\n"
                f"🧾 مع العمولة : {total:,} ل.س"
            )
        )
        process_queue(bot)
        bot.answer_callback_query(call.id, "✅ تم إرسال الطلب للإدارة")
        bot.send_message(call.message.chat.id, "✅ تم إرسال طلب الفاتورة للإدارة، بانتظار الموافقة.")

    # ------ موافقة/رفض الإدارة ------

    @bot.callback_query_handler(func=lambda c: c.data.startswith("admin_accept_mtn_bill_"))
    def admin_accept_mtn_bill(call):
        uid = int(call.data.split("_")[-1])
        st = user_states.get(uid, {})
        total = st.get("amount_with_fee", 0)
        number = st.get("number", "")
        amount = st.get("amount", 0)

        if not has_sufficient_balance(uid, total):
            bal = get_balance(uid)
            bot.send_message(uid, f"❌ رصيدك {bal:,} ل.س والمطلوب {total:,} ل.س.")
            return bot.answer_callback_query(call.id, "❌")

        pending_users.discard(uid)
        _update_balance(uid, -total)
        add_purchase(uid, 0, "فاتورة MTN", total, number)
        bot.send_message(
            uid,
            f"✅ تم دفع فاتورة الرقم <code>{number}</code>\n"
            f"بمبلغ {amount:,} ل.س وخصم إجمالي {total:,} ل.س من محفظتك.",
            parse_mode="HTML"
        )
        bot.answer_callback_query(call.id, "✅")
        user_states.pop(uid, None)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("admin_reject_mtn_bill_"))
    def admin_reject_mtn_bill(call):
        uid = int(call.data.split("_")[-1])
        pending_users.discard(uid)
        bot.send_message(uid, "❌ تم رفض طلب دفع الفاتورة من الإدارة.")
        bot.answer_callback_query(call.id, "❌ تم رفض الطلب")
        user_states.pop(uid, None)
def register(bot):
    register_bill_and_units(bot, {})
