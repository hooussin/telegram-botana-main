from telebot import types
import math
import logging
from services.wallet_service import (
    get_balance,
    add_purchase,
    register_user_if_not_exist,
)
from config import ADMIN_MAIN_ID
from services.queue_service import add_pending_request, process_queue

# قوائم الوحدات
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

def make_inline_buttons(*buttons):
    kb = types.InlineKeyboardMarkup()
    for text, data in buttons:
        kb.add(types.InlineKeyboardButton(text, callback_data=data))
    return kb

def is_valid_phone(number):
    return number.isdigit() and number.startswith("09") and len(number) == 10

# -----------------------------------------------------------------------------
# تسجيل البوت في ملف رئيسي (عادة باسم register أو حسب نظامك)
def register(bot):

    # ================== شحن وحدات سيرياتيل ==================
    @bot.message_handler(func=lambda msg: msg.text == "🔋 شحن وحدات سيرياتيل")
    def syr_units_menu(msg):
        user_id = msg.from_user.id
        register_user_if_not_exist(user_id, msg.from_user.full_name)
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        for u in SYRIATEL_UNITS:
            kb.add(u["name"])
        kb.add("⬅️ رجوع")
        bot.send_message(msg.chat.id, "اختر الكمية المطلوبة:", reply_markup=kb)
        user_states[user_id] = {"step": "syr_unit_select"}

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "syr_unit_select")
    def syr_unit_select(msg):
        user_id = msg.from_user.id
        name = msg.text.strip()
        unit = next((u for u in SYRIATEL_UNITS if u["name"] == name), None)
        if not unit:
            bot.send_message(msg.chat.id, "❌ يرجى اختيار كمية صحيحة من القائمة.")
            return
        user_states[user_id] = {"step": "syr_unit_number", "unit": unit}
        bot.send_message(msg.chat.id, "أدخل رقم الهاتف المراد شحنه (يجب أن يبدأ بـ 09 وعدد الأرقام 10):")

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "syr_unit_number")
    def syr_unit_number(msg):
        user_id = msg.from_user.id
        number = msg.text.strip()
        if not is_valid_phone(number):
            bot.send_message(msg.chat.id, "⚠️ الرقم غير صحيح. يجب أن يبدأ بـ 09 وأن يكون 10 أرقام.")
            return
        state = user_states[user_id]
        unit = state["unit"]
        price = unit["price"]
        balance = get_balance(user_id)
        if balance < price:
            bot.send_message(msg.chat.id, f"❌ رصيدك غير كافٍ. رصيدك الحالي: {balance:,} ل.س. السعر المطلوب: {price:,} ل.س.")
            user_states.pop(user_id, None)
            return
        state["number"] = number
        state["step"] = "syr_unit_confirm"
        kb = make_inline_buttons(
            ("❌ إلغاء", "cancel_all"),
            ("✔️ تأكيد الشراء", "syr_unit_final_confirm")
        )
        bot.send_message(
            msg.chat.id,
            f"هل أنت متأكد من شراء {unit['name']} بسعر {unit['price']:,} ل.س للرقم:\n{number}؟",
            reply_markup=kb
        )

    @bot.callback_query_handler(func=lambda call: call.data == "syr_unit_final_confirm")
    def syr_unit_final_confirm(call):
        user_id = call.from_user.id
        state = user_states.get(user_id)
        if not state:
            bot.send_message(call.message.chat.id, "حدث خطأ يرجى البدء من جديد.")
            return
        unit = state["unit"]
        price = unit["price"]
        number = state["number"]
        admin_msg = (
            f"🔴 وحدات سيرياتيل:\n"
            f"👤 المستخدم: <code>{user_id}</code>\n"
            f"📱 الرقم: <code>{number}</code>\n"
            f"💵 الكمية: {unit['name']}\n"
            f"💰 السعر: {price:,} ل.س"
        )
        add_pending_request(
            user_id=user_id,
            username=call.from_user.username,
            request_text=admin_msg
        )
        bot.send_message(call.message.chat.id, "✅ تم إرسال طلبك للإدارة. سيتم معالجته خلال دقائق قليلة. لن تتمكن من تقديم طلب جديد حتى معالجة هذا الطلب.")
        process_queue(bot)
        user_states.pop(user_id, None)
    # ================== شحن وحدات MTN ==================
    @bot.message_handler(func=lambda msg: msg.text == "🔋 شحن وحدات MTN")
    def mtn_units_menu(msg):
        user_id = msg.from_user.id
        register_user_if_not_exist(user_id, msg.from_user.full_name)
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        for u in MTN_UNITS:
            kb.add(u["name"])
        kb.add("⬅️ رجوع")
        bot.send_message(msg.chat.id, "اختر الكمية المطلوبة:", reply_markup=kb)
        user_states[user_id] = {"step": "mtn_unit_select"}

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "mtn_unit_select")
    def mtn_unit_select(msg):
        user_id = msg.from_user.id
        name = msg.text.strip()
        unit = next((u for u in MTN_UNITS if u["name"] == name), None)
        if not unit:
            bot.send_message(msg.chat.id, "❌ يرجى اختيار كمية صحيحة من القائمة.")
            return
        user_states[user_id] = {"step": "mtn_unit_number", "unit": unit}
        bot.send_message(msg.chat.id, "أدخل رقم الهاتف المراد شحنه (يجب أن يبدأ بـ 09 وعدد الأرقام 10):")

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "mtn_unit_number")
    def mtn_unit_number(msg):
        user_id = msg.from_user.id
        number = msg.text.strip()
        if not is_valid_phone(number):
            bot.send_message(msg.chat.id, "⚠️ الرقم غير صحيح. يجب أن يبدأ بـ 09 وأن يكون 10 أرقام.")
            return
        state = user_states[user_id]
        unit = state["unit"]
        price = unit["price"]
        balance = get_balance(user_id)
        if balance < price:
            bot.send_message(msg.chat.id, f"❌ رصيدك غير كافٍ. رصيدك الحالي: {balance:,} ل.س. السعر المطلوب: {price:,} ل.س.")
            user_states.pop(user_id, None)
            return
        state["number"] = number
        state["step"] = "mtn_unit_confirm"
        kb = make_inline_buttons(
            ("❌ إلغاء", "cancel_all"),
            ("✔️ تأكيد الشراء", "mtn_unit_final_confirm")
        )
        bot.send_message(
            msg.chat.id,
            f"هل أنت متأكد من شراء {unit['name']} بسعر {unit['price']:,} ل.س للرقم:\n{number}؟",
            reply_markup=kb
        )

    @bot.callback_query_handler(func=lambda call: call.data == "mtn_unit_final_confirm")
    def mtn_unit_final_confirm(call):
        user_id = call.from_user.id
        state = user_states.get(user_id)
        if not state:
            bot.send_message(call.message.chat.id, "حدث خطأ يرجى البدء من جديد.")
            return
        unit = state["unit"]
        price = unit["price"]
        number = state["number"]
        admin_msg = (
            f"🟡 وحدات MTN:\n"
            f"👤 المستخدم: <code>{user_id}</code>\n"
            f"📱 الرقم: <code>{number}</code>\n"
            f"💵 الكمية: {unit['name']}\n"
            f"💰 السعر: {price:,} ل.س"
        )
        add_pending_request(
            user_id=user_id,
            username=call.from_user.username,
            request_text=admin_msg
        )
        bot.send_message(call.message.chat.id, "✅ تم إرسال طلبك للإدارة. سيتم معالجته خلال دقائق قليلة. لن تتمكن من تقديم طلب جديد حتى معالجة هذا الطلب.")
        process_queue(bot)
        user_states.pop(user_id, None)

    # ================== دفع فاتورة سيرياتيل ==================
    @bot.message_handler(func=lambda msg: msg.text == "💳 دفع فاتورة سيرياتيل")
    def syr_bill_start(msg):
        user_id = msg.from_user.id
        register_user_if_not_exist(user_id, msg.from_user.full_name)
        user_states[user_id] = {"step": "syr_bill_number"}
        bot.send_message(msg.chat.id, "أدخل رقم الهاتف المراد دفع الفاتورة عنه (يجب أن يبدأ بـ 09 وعدد الأرقام 10):")

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "syr_bill_number")
    def syr_bill_number(msg):
        user_id = msg.from_user.id
        number = msg.text.strip()
        if not is_valid_phone(number):
            bot.send_message(msg.chat.id, "⚠️ الرقم غير صحيح. يجب أن يبدأ بـ 09 وأن يكون 10 أرقام.")
            return
        user_states[user_id]["number"] = number
        user_states[user_id]["step"] = "syr_bill_amount"
        bot.send_message(msg.chat.id, "أدخل قيمة الفاتورة (ل.س):")

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "syr_bill_amount")
    def syr_bill_amount(msg):
        user_id = msg.from_user.id
        try:
            amount = int(msg.text.strip().replace(",", ""))
        except Exception:
            bot.send_message(msg.chat.id, "❌ الرجاء إدخال رقم صحيح لقيمة الفاتورة.")
            return
        balance = get_balance(user_id)
        if balance < amount:
            bot.send_message(msg.chat.id, f"❌ رصيدك غير كافٍ. رصيدك الحالي: {balance:,} ل.س. قيمة الفاتورة: {amount:,} ل.س.")
            user_states.pop(user_id, None)
            return
        number = user_states[user_id]["number"]
        user_states[user_id] = {"step": "syr_bill_confirm", "number": number, "amount": amount}
        kb = make_inline_buttons(
            ("❌ إلغاء", "cancel_all"),
            ("✔️ تأكيد الدفع", "syr_bill_final_confirm")
        )
        bot.send_message(
            msg.chat.id,
            f"هل أنت متأكد من دفع فاتورة سيرياتيل بقيمة {amount:,} ل.س للرقم:\n{number}؟",
            reply_markup=kb
        )

    @bot.callback_query_handler(func=lambda call: call.data == "syr_bill_final_confirm")
    def syr_bill_final_confirm(call):
        user_id = call.from_user.id
        state = user_states.get(user_id)
        if not state:
            bot.send_message(call.message.chat.id, "حدث خطأ يرجى البدء من جديد.")
            return
        amount = state["amount"]
        number = state["number"]
        admin_msg = (
            f"💳 دفع فاتورة سيرياتيل:\n"
            f"👤 المستخدم: <code>{user_id}</code>\n"
            f"📱 الرقم: <code>{number}</code>\n"
            f"💰 القيمة: {amount:,} ل.س"
        )
        add_pending_request(
            user_id=user_id,
            username=call.from_user.username,
            request_text=admin_msg
        )
        bot.send_message(call.message.chat.id, "✅ تم إرسال طلبك للإدارة. سيتم معالجته خلال دقائق قليلة. لن تتمكن من تقديم طلب جديد حتى معالجة هذا الطلب.")
        process_queue(bot)
        user_states.pop(user_id, None)

    # ================== دفع فاتورة MTN ==================
    @bot.message_handler(func=lambda msg: msg.text == "💳 دفع فاتورة MTN")
    def mtn_bill_start(msg):
        user_id = msg.from_user.id
        register_user_if_not_exist(user_id, msg.from_user.full_name)
        user_states[user_id] = {"step": "mtn_bill_number"}
        bot.send_message(msg.chat.id, "أدخل رقم الهاتف المراد دفع الفاتورة عنه (يجب أن يبدأ بـ 09 وعدد الأرقام 10):")

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "mtn_bill_number")
    def mtn_bill_number(msg):
        user_id = msg.from_user.id
        number = msg.text.strip()
        if not is_valid_phone(number):
            bot.send_message(msg.chat.id, "⚠️ الرقم غير صحيح. يجب أن يبدأ بـ 09 وأن يكون 10 أرقام.")
            return
        user_states[user_id]["number"] = number
        user_states[user_id]["step"] = "mtn_bill_amount"
        bot.send_message(msg.chat.id, "أدخل قيمة الفاتورة (ل.س):")

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "mtn_bill_amount")
    def mtn_bill_amount(msg):
        user_id = msg.from_user.id
        try:
            amount = int(msg.text.strip().replace(",", ""))
        except Exception:
            bot.send_message(msg.chat.id, "❌ الرجاء إدخال رقم صحيح لقيمة الفاتورة.")
            return
        balance = get_balance(user_id)
        if balance < amount:
            bot.send_message(msg.chat.id, f"❌ رصيدك غير كافٍ. رصيدك الحالي: {balance:,} ل.س. قيمة الفاتورة: {amount:,} ل.س.")
            user_states.pop(user_id, None)
            return
        number = user_states[user_id]["number"]
        user_states[user_id] = {"step": "mtn_bill_confirm", "number": number, "amount": amount}
        kb = make_inline_buttons(
            ("❌ إلغاء", "cancel_all"),
            ("✔️ تأكيد الدفع", "mtn_bill_final_confirm")
        )
        bot.send_message(
            msg.chat.id,
            f"هل أنت متأكد من دفع فاتورة MTN بقيمة {amount:,} ل.س للرقم:\n{number}؟",
            reply_markup=kb
        )

    @bot.callback_query_handler(func=lambda call: call.data == "mtn_bill_final_confirm")
    def mtn_bill_final_confirm(call):
        user_id = call.from_user.id
        state = user_states.get(user_id)
        if not state:
            bot.send_message(call.message.chat.id, "حدث خطأ يرجى البدء من جديد.")
            return
        amount = state["amount"]
        number = state["number"]
        admin_msg = (
            f"💳 دفع فاتورة MTN:\n"
            f"👤 المستخدم: <code>{user_id}</code>\n"
            f"📱 الرقم: <code>{number}</code>\n"
            f"💰 القيمة: {amount:,} ل.س"
        )
        add_pending_request(
            user_id=user_id,
            username=call.from_user.username,
            request_text=admin_msg
        )
        bot.send_message(call.message.chat.id, "✅ تم إرسال طلبك للإدارة. سيتم معالجته خلال دقائق قليلة. لن تتمكن من تقديم طلب جديد حتى معالجة هذا الطلب.")
        process_queue(bot)
        user_states.pop(user_id, None)
    # ============= دعم الرجوع والإلغاء في كل المراحل =============
    @bot.message_handler(func=lambda msg: msg.text == "⬅️ رجوع")
    def handle_back(msg):
        user_id = msg.from_user.id
        user_states.pop(user_id, None)
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("🔋 شحن وحدات سيرياتيل", "🔋 شحن وحدات MTN")
        kb.add("💳 دفع فاتورة سيرياتيل", "💳 دفع فاتورة MTN")
        kb.add("🏠 الرئيسية")
        bot.send_message(msg.chat.id, "تم الرجوع. اختر خدمة:", reply_markup=kb)

    @bot.callback_query_handler(func=lambda call: call.data == "cancel_all")
    def handle_cancel(call):
        user_id = call.from_user.id
        user_states.pop(user_id, None)
        bot.send_message(call.message.chat.id, "❌ تم إلغاء العملية.")
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("🔋 شحن وحدات سيرياتيل", "🔋 شحن وحدات MTN")
        kb.add("💳 دفع فاتورة سيرياتيل", "💳 دفع فاتورة MTN")
        kb.add("🏠 الرئيسية")
        bot.send_message(call.message.chat.id, "اختر خدمة:", reply_markup=kb)

    # ============= معالجة رسائل غير مفهومة في أي مرحلة =============
    @bot.message_handler(func=lambda msg: True)
    def fallback_handler(msg):
        user_id = msg.from_user.id
        if user_states.get(user_id):
            bot.send_message(msg.chat.id, "⚠️ يرجى اتباع التعليمات بدقة أو الضغط على 'رجوع' لإعادة البدء.")
        else:
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
            kb.add("🔋 شحن وحدات سيرياتيل", "🔋 شحن وحدات MTN")
            kb.add("💳 دفع فاتورة سيرياتيل", "💳 دفع فاتورة MTN")
            kb.add("🏠 الرئيسية")
            bot.send_message(msg.chat.id, "مرحباً! اختر إحدى الخدمات:", reply_markup=kb)

    # ============= يمكنك هنا إضافة أي قوائم أو خدمات أخرى لم يتم تعديلها =============
    # ... جميع الدوال الأصلية الأخرى (كهرباء، ماء، نت... إلخ) تظل كما هي وتُعدل بنفس الأسلوب إذا رغبت
