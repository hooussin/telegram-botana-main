import logging
import re
import time
from telebot import types
from datetime import datetime, timedelta

from services.queue_service import add_pending_request
from services.wallet_service import get_balance, deduct_balance

# هنا متغيرات الحالة الخاصة بالمستخدمين
user_states = {}

# توليد أزرار تلقائية
def make_inline_buttons(*buttons):
    markup = types.InlineKeyboardMarkup()
    for btn in buttons:
        markup.add(types.InlineKeyboardButton(btn[0], callback_data=btn[1]))
    return markup

# =========== دوال الشحن الأساسية ===========

def register(bot):
    # شحن وحدات سيرياتيل
    @bot.message_handler(func=lambda msg: msg.text == "🔋 شحن وحدات سيرياتيل")
    def handle_syr_unit(msg):
        user_id = msg.from_user.id
        user_states[user_id] = {
            "step": "syr_unit_number"
        }
        bot.send_message(msg.chat.id, "أدخل رقم الموبايل (يبدأ بـ09):")

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "syr_unit_number")
    def syr_unit_number(msg):
        user_id = msg.from_user.id
        number = msg.text.strip()
        # شرط التحقق من الرقم
        if not (number.isdigit() and number.startswith("09") and len(number) == 10):
            bot.send_message(msg.chat.id, "⚠️ أدخل رقم هاتف صحيح يبدأ بـ 09 ومؤلف من 10 أرقام.")
            return
        user_states[user_id]["number"] = number
        user_states[user_id]["step"] = "syr_unit_choose"
        # افتراضية أمثلة وحدات
        units = [
            {"id": 1, "name": "500 وحدة", "price": 5000},
            {"id": 2, "name": "1000 وحدة", "price": 10000},
        ]
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for unit in units:
            markup.add(unit["name"])
        markup.add("⬅️ رجوع")
        bot.send_message(msg.chat.id, "اختر الباقة المطلوبة:", reply_markup=markup)

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "syr_unit_choose")
    def syr_unit_choose(msg):
        user_id = msg.from_user.id
        unit_name = msg.text.strip()
        # أمثلة أسعار، يمكنك ربطها من قاعدة بياناتك
        unit_prices = {"500 وحدة": 5000, "1000 وحدة": 10000}
        if unit_name not in unit_prices:
            bot.send_message(msg.chat.id, "❗ يرجى اختيار باقة من الخيارات.")
            return
        user_states[user_id]["unit"] = {
            "name": unit_name,
            "price": unit_prices[unit_name]
        }
        user_states[user_id]["step"] = "syr_unit_confirm"
        kb = make_inline_buttons(
            ("❌ إلغاء", "cancel_all"),
            ("✔️ تأكيد الشراء", "syr_unit_final_confirm")
        )
        bot.send_message(
            msg.chat.id,
            f"هل أنت متأكد من شراء {unit_name} بسعر {unit_prices[unit_name]:,} ل.س للرقم:\n{user_states[user_id]['number']}؟",
            reply_markup=kb
        )

    @bot.callback_query_handler(func=lambda call: call.data == "syr_unit_final_confirm")
    def syr_unit_final_confirm(call):
        user_id = call.from_user.id
        state = user_states.get(user_id)
        if not state or "unit" not in state or "number" not in state:
            bot.answer_callback_query(call.id, "❌ حدث خطأ! أعد العملية من جديد.")
            return
        number = state["number"]
        unit = state["unit"]
        price = unit["price"]
        balance = get_balance(user_id)
        if balance < price:
            bot.send_message(call.message.chat.id, f"❌ رصيدك غير كافٍ. سعر الباقة {price:,} ل.س. رصيدك الحالي {balance:,} ل.س.")
            return
        # إضافة الطلب للطابور (queue)
        admin_msg = (
            f"🆕 طلب جديد لشحن وحدات سيرياتيل:\n"
            f"👤 العميل: <code>{call.from_user.first_name}</code>\n"
            f"🆔: <code>{user_id}</code>\n"
            f"📞 رقم الهاتف: <code>{number}</code>\n"
            f"💳 الباقة: {unit['name']}\n"
            f"💵 السعر: {price:,} ل.س\n"
        )
        add_pending_request(
            user_id=user_id,
            username=call.from_user.username,
            request_text=admin_msg
        )
        bot.send_message(
            user_id,
            "✅ تم إرسال طلبك للإدارة. سيتم معالجة طلبك خلال 1 إلى 4 دقائق."
        )
        user_states.pop(user_id, None)
    # ================= وحدات MTN ==================
    @bot.message_handler(func=lambda msg: msg.text == "🔋 شحن وحدات MTN")
    def handle_mtn_unit(msg):
        user_id = msg.from_user.id
        user_states[user_id] = {
            "step": "mtn_unit_number"
        }
        bot.send_message(msg.chat.id, "أدخل رقم الموبايل (يبدأ بـ09):")

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "mtn_unit_number")
    def mtn_unit_number(msg):
        user_id = msg.from_user.id
        number = msg.text.strip()
        if not (number.isdigit() and number.startswith("09") and len(number) == 10):
            bot.send_message(msg.chat.id, "⚠️ أدخل رقم هاتف صحيح يبدأ بـ 09 ومؤلف من 10 أرقام.")
            return
        user_states[user_id]["number"] = number
        user_states[user_id]["step"] = "mtn_unit_choose"
        units = [
            {"id": 1, "name": "500 وحدة", "price": 5200},
            {"id": 2, "name": "1000 وحدة", "price": 10400},
        ]
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for unit in units:
            markup.add(unit["name"])
        markup.add("⬅️ رجوع")
        bot.send_message(msg.chat.id, "اختر الباقة المطلوبة:", reply_markup=markup)

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "mtn_unit_choose")
    def mtn_unit_choose(msg):
        user_id = msg.from_user.id
        unit_name = msg.text.strip()
        unit_prices = {"500 وحدة": 5200, "1000 وحدة": 10400}
        if unit_name not in unit_prices:
            bot.send_message(msg.chat.id, "❗ يرجى اختيار باقة من الخيارات.")
            return
        user_states[user_id]["unit"] = {
            "name": unit_name,
            "price": unit_prices[unit_name]
        }
        user_states[user_id]["step"] = "mtn_unit_confirm"
        kb = make_inline_buttons(
            ("❌ إلغاء", "cancel_all"),
            ("✔️ تأكيد الشراء", "mtn_unit_final_confirm")
        )
        bot.send_message(
            msg.chat.id,
            f"هل أنت متأكد من شراء {unit_name} بسعر {unit_prices[unit_name]:,} ل.س للرقم:\n{user_states[user_id]['number']}؟",
            reply_markup=kb
        )

    @bot.callback_query_handler(func=lambda call: call.data == "mtn_unit_final_confirm")
    def mtn_unit_final_confirm(call):
        user_id = call.from_user.id
        state = user_states.get(user_id)
        if not state or "unit" not in state or "number" not in state:
            bot.answer_callback_query(call.id, "❌ حدث خطأ! أعد العملية من جديد.")
            return
        number = state["number"]
        unit = state["unit"]
        price = unit["price"]
        balance = get_balance(user_id)
        if balance < price:
            bot.send_message(call.message.chat.id, f"❌ رصيدك غير كافٍ. سعر الباقة {price:,} ل.س. رصيدك الحالي {balance:,} ل.س.")
            return
        # إضافة الطلب للطابور
        admin_msg = (
            f"🆕 طلب جديد لشحن وحدات MTN:\n"
            f"👤 العميل: <code>{call.from_user.first_name}</code>\n"
            f"🆔: <code>{user_id}</code>\n"
            f"📞 رقم الهاتف: <code>{number}</code>\n"
            f"💳 الباقة: {unit['name']}\n"
            f"💵 السعر: {price:,} ل.س\n"
        )
        add_pending_request(
            user_id=user_id,
            username=call.from_user.username,
            request_text=admin_msg
        )
        bot.send_message(
            user_id,
            "✅ تم إرسال طلبك للإدارة. سيتم معالجة طلبك خلال 1 إلى 4 دقائق."
        )
        user_states.pop(user_id, None)

    # ================= دفع فاتورة سيرياتيل ==================
    @bot.message_handler(func=lambda msg: msg.text == "💳 دفع فاتورة سيرياتيل")
    def handle_syr_bill(msg):
        user_id = msg.from_user.id
        user_states[user_id] = {
            "step": "syr_bill_number"
        }
        bot.send_message(msg.chat.id, "أدخل رقم الموبايل (يبدأ بـ09):")

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "syr_bill_number")
    def syr_bill_number(msg):
        user_id = msg.from_user.id
        number = msg.text.strip()
        if not (number.isdigit() and number.startswith("09") and len(number) == 10):
            bot.send_message(msg.chat.id, "⚠️ أدخل رقم هاتف صحيح يبدأ بـ 09 ومؤلف من 10 أرقام.")
            return
        user_states[user_id]["number"] = number
        user_states[user_id]["step"] = "syr_bill_amount"
        bot.send_message(msg.chat.id, "أدخل قيمة الفاتورة (بالليرة السورية):")

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "syr_bill_amount")
    def syr_bill_amount(msg):
        user_id = msg.from_user.id
        try:
            amount = int(msg.text.strip())
        except Exception:
            bot.send_message(msg.chat.id, "❗ أدخل رقم صحيح لقيمة الفاتورة.")
            return
        if amount < 1000 or amount > 200_000:
            bot.send_message(msg.chat.id, "❗ المبلغ يجب أن يكون بين 1,000 و 200,000 ل.س.")
            return
        user_states[user_id]["amount"] = amount
        user_states[user_id]["step"] = "syr_bill_confirm"
        # عمولة مثلاً 500 ل.س
        fee = 500
        total = amount + fee
        kb = make_inline_buttons(
            ("❌ إلغاء", "cancel_all"),
            ("✔️ تأكيد الدفع", "syr_bill_final_confirm")
        )
        bot.send_message(
            msg.chat.id,
            f"هل أنت متأكد من دفع فاتورة سيرياتيل بقيمة {amount:,} ل.س للرقم:\n{user_states[user_id]['number']}؟\n\nعمولة الخدمة: {fee:,} ل.س\nالمبلغ الكلي: {total:,} ل.س",
            reply_markup=kb
        )
    @bot.callback_query_handler(func=lambda call: call.data == "syr_bill_final_confirm")
    def syr_bill_final_confirm(call):
        user_id = call.from_user.id
        state = user_states.get(user_id)
        if not state or "number" not in state or "amount" not in state:
            bot.answer_callback_query(call.id, "❌ حدث خطأ! أعد العملية من جديد.")
            return
        number = state["number"]
        amount = state["amount"]
        fee = 500
        total = amount + fee
        balance = get_balance(user_id)
        if balance < total:
            bot.send_message(call.message.chat.id, f"❌ رصيدك غير كافٍ. مجموع الفاتورة مع العمولة {total:,} ل.س. رصيدك الحالي {balance:,} ل.س.")
            return
        # إضافة الطلب للطابور
        admin_msg = (
            f"🆕 طلب جديد لدفع فاتورة سيرياتيل:\n"
            f"👤 العميل: <code>{call.from_user.first_name}</code>\n"
            f"🆔: <code>{user_id}</code>\n"
            f"📞 رقم الهاتف: <code>{number}</code>\n"
            f"💵 المبلغ: {amount:,} ل.س\n"
            f"💸 عمولة الخدمة: {fee:,} ل.س\n"
            f"💳 المجموع: {total:,} ل.س\n"
        )
        add_pending_request(
            user_id=user_id,
            username=call.from_user.username,
            request_text=admin_msg
        )
        bot.send_message(
            user_id,
            "✅ تم إرسال طلبك للإدارة. سيتم معالجة طلبك خلال 1 إلى 4 دقائق."
        )
        user_states.pop(user_id, None)

    # ================= دفع فاتورة MTN ==================
    @bot.message_handler(func=lambda msg: msg.text == "💳 دفع فاتورة MTN")
    def handle_mtn_bill(msg):
        user_id = msg.from_user.id
        user_states[user_id] = {
            "step": "mtn_bill_number"
        }
        bot.send_message(msg.chat.id, "أدخل رقم الموبايل (يبدأ بـ09):")

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "mtn_bill_number")
    def mtn_bill_number(msg):
        user_id = msg.from_user.id
        number = msg.text.strip()
        if not (number.isdigit() and number.startswith("09") and len(number) == 10):
            bot.send_message(msg.chat.id, "⚠️ أدخل رقم هاتف صحيح يبدأ بـ 09 ومؤلف من 10 أرقام.")
            return
        user_states[user_id]["number"] = number
        user_states[user_id]["step"] = "mtn_bill_amount"
        bot.send_message(msg.chat.id, "أدخل قيمة الفاتورة (بالليرة السورية):")

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "mtn_bill_amount")
    def mtn_bill_amount(msg):
        user_id = msg.from_user.id
        try:
            amount = int(msg.text.strip())
        except Exception:
            bot.send_message(msg.chat.id, "❗ أدخل رقم صحيح لقيمة الفاتورة.")
            return
        if amount < 1000 or amount > 200_000:
            bot.send_message(msg.chat.id, "❗ المبلغ يجب أن يكون بين 1,000 و 200,000 ل.س.")
            return
        user_states[user_id]["amount"] = amount
        user_states[user_id]["step"] = "mtn_bill_confirm"
        fee = 500
        total = amount + fee
        kb = make_inline_buttons(
            ("❌ إلغاء", "cancel_all"),
            ("✔️ تأكيد الدفع", "mtn_bill_final_confirm")
        )
        bot.send_message(
            msg.chat.id,
            f"هل أنت متأكد من دفع فاتورة MTN بقيمة {amount:,} ل.س للرقم:\n{user_states[user_id]['number']}؟\n\nعمولة الخدمة: {fee:,} ل.س\nالمبلغ الكلي: {total:,} ل.س",
            reply_markup=kb
        )

    @bot.callback_query_handler(func=lambda call: call.data == "mtn_bill_final_confirm")
    def mtn_bill_final_confirm(call):
        user_id = call.from_user.id
        state = user_states.get(user_id)
        if not state or "number" not in state or "amount" not in state:
            bot.answer_callback_query(call.id, "❌ حدث خطأ! أعد العملية من جديد.")
            return
        number = state["number"]
        amount = state["amount"]
        fee = 500
        total = amount + fee
        balance = get_balance(user_id)
        if balance < total:
            bot.send_message(call.message.chat.id, f"❌ رصيدك غير كافٍ. مجموع الفاتورة مع العمولة {total:,} ل.س. رصيدك الحالي {balance:,} ل.س.")
            return
        admin_msg = (
            f"🆕 طلب جديد لدفع فاتورة MTN:\n"
            f"👤 العميل: <code>{call.from_user.first_name}</code>\n"
            f"🆔: <code>{user_id}</code>\n"
            f"📞 رقم الهاتف: <code>{number}</code>\n"
            f"💵 المبلغ: {amount:,} ل.س\n"
            f"💸 عمولة الخدمة: {fee:,} ل.س\n"
            f"💳 المجموع: {total:,} ل.س\n"
        )
        add_pending_request(
            user_id=user_id,
            username=call.from_user.username,
            request_text=admin_msg
        )
        bot.send_message(
            user_id,
            "✅ تم إرسال طلبك للإدارة. سيتم معالجة طلبك خلال 1 إلى 4 دقائق."
        )
        user_states.pop(user_id, None)
    # ================= دفع فواتير الكهرباء ==================
    @bot.message_handler(func=lambda msg: msg.text == "💡 دفع فاتورة كهرباء")
    def handle_elec_bill(msg):
        user_id = msg.from_user.id
        user_states[user_id] = {
            "step": "elec_bill_number"
        }
        bot.send_message(msg.chat.id, "أدخل رقم الاشتراك الكهربائي:")

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "elec_bill_number")
    def elec_bill_number(msg):
        user_id = msg.from_user.id
        number = msg.text.strip()
        # تحقق أن الرقم فقط أرقام
        if not number.isdigit() or len(number) < 6:
            bot.send_message(msg.chat.id, "⚠️ أدخل رقم اشتراك صحيح (أرقام فقط).")
            return
        user_states[user_id]["number"] = number
        user_states[user_id]["step"] = "elec_bill_amount"
        bot.send_message(msg.chat.id, "أدخل قيمة الفاتورة (بالليرة السورية):")

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "elec_bill_amount")
    def elec_bill_amount(msg):
        user_id = msg.from_user.id
        try:
            amount = int(msg.text.strip())
        except Exception:
            bot.send_message(msg.chat.id, "❗ أدخل رقم صحيح لقيمة الفاتورة.")
            return
        if amount < 500 or amount > 500_000:
            bot.send_message(msg.chat.id, "❗ المبلغ يجب أن يكون بين 500 و 500,000 ل.س.")
            return
        user_states[user_id]["amount"] = amount
        user_states[user_id]["step"] = "elec_bill_confirm"
        fee = 1000
        total = amount + fee
        kb = make_inline_buttons(
            ("❌ إلغاء", "cancel_all"),
            ("✔️ تأكيد الدفع", "elec_bill_final_confirm")
        )
        bot.send_message(
            msg.chat.id,
            f"هل أنت متأكد من دفع فاتورة كهرباء بقيمة {amount:,} ل.س للاشتراك:\n{user_states[user_id]['number']}؟\n\nعمولة الخدمة: {fee:,} ل.س\nالمبلغ الكلي: {total:,} ل.س",
            reply_markup=kb
        )

    @bot.callback_query_handler(func=lambda call: call.data == "elec_bill_final_confirm")
    def elec_bill_final_confirm(call):
        user_id = call.from_user.id
        state = user_states.get(user_id)
        if not state or "number" not in state or "amount" not in state:
            bot.answer_callback_query(call.id, "❌ حدث خطأ! أعد العملية من جديد.")
            return
        number = state["number"]
        amount = state["amount"]
        fee = 1000
        total = amount + fee
        balance = get_balance(user_id)
        if balance < total:
            bot.send_message(call.message.chat.id, f"❌ رصيدك غير كافٍ. مجموع الفاتورة مع العمولة {total:,} ل.س. رصيدك الحالي {balance:,} ل.س.")
            return
        admin_msg = (
            f"🆕 طلب جديد لدفع فاتورة كهرباء:\n"
            f"👤 العميل: <code>{call.from_user.first_name}</code>\n"
            f"🆔: <code>{user_id}</code>\n"
            f"🔢 رقم الاشتراك: <code>{number}</code>\n"
            f"💵 المبلغ: {amount:,} ل.س\n"
            f"💸 عمولة الخدمة: {fee:,} ل.س\n"
            f"💳 المجموع: {total:,} ل.س\n"
        )
        add_pending_request(
            user_id=user_id,
            username=call.from_user.username,
            request_text=admin_msg
        )
        bot.send_message(
            user_id,
            "✅ تم إرسال طلبك للإدارة. سيتم معالجة طلبك خلال 1 إلى 4 دقائق."
        )
        user_states.pop(user_id, None)

    # ================= دفع فاتورة ماء ==================
    @bot.message_handler(func=lambda msg: msg.text == "🚰 دفع فاتورة ماء")
    def handle_water_bill(msg):
        user_id = msg.from_user.id
        user_states[user_id] = {
            "step": "water_bill_number"
        }
        bot.send_message(msg.chat.id, "أدخل رقم اشتراك المياه:")

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "water_bill_number")
    def water_bill_number(msg):
        user_id = msg.from_user.id
        number = msg.text.strip()
        if not number.isdigit() or len(number) < 6:
            bot.send_message(msg.chat.id, "⚠️ أدخل رقم اشتراك صحيح (أرقام فقط).")
            return
        user_states[user_id]["number"] = number
        user_states[user_id]["step"] = "water_bill_amount"
        bot.send_message(msg.chat.id, "أدخل قيمة الفاتورة (بالليرة السورية):")

    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id, {}).get("step") == "water_bill_amount")
    def water_bill_amount(msg):
        user_id = msg.from_user.id
        try:
            amount = int(msg.text.strip())
        except Exception:
            bot.send_message(msg.chat.id, "❗ أدخل رقم صحيح لقيمة الفاتورة.")
            return
        if amount < 500 or amount > 500_000:
            bot.send_message(msg.chat.id, "❗ المبلغ يجب أن يكون بين 500 و 500,000 ل.س.")
            return
        user_states[user_id]["amount"] = amount
        user_states[user_id]["step"] = "water_bill_confirm"
        fee = 1000
        total = amount + fee
        kb = make_inline_buttons(
            ("❌ إلغاء", "cancel_all"),
            ("✔️ تأكيد الدفع", "water_bill_final_confirm")
        )
        bot.send_message(
            msg.chat.id,
            f"هل أنت متأكد من دفع فاتورة ماء بقيمة {amount:,} ل.س للاشتراك:\n{user_states[user_id]['number']}؟\n\nعمولة الخدمة: {fee:,} ل.س\nالمبلغ الكلي: {total:,} ل.س",
            reply_markup=kb
        )
    @bot.callback_query_handler(func=lambda call: call.data == "water_bill_final_confirm")
    def water_bill_final_confirm(call):
        user_id = call.from_user.id
        state = user_states.get(user_id)
        if not state or "number" not in state or "amount" not in state:
            bot.answer_callback_query(call.id, "❌ حدث خطأ! أعد العملية من جديد.")
            return
        number = state["number"]
        amount = state["amount"]
        fee = 1000
        total = amount + fee
        balance = get_balance(user_id)
        if balance < total:
            bot.send_message(call.message.chat.id, f"❌ رصيدك غير كافٍ. مجموع الفاتورة مع العمولة {total:,} ل.س. رصيدك الحالي {balance:,} ل.س.")
            return
        admin_msg = (
            f"🆕 طلب جديد لدفع فاتورة ماء:\n"
            f"👤 العميل: <code>{call.from_user.first_name}</code>\n"
            f"🆔: <code>{user_id}</code>\n"
            f"🔢 رقم الاشتراك: <code>{number}</code>\n"
            f"💵 المبلغ: {amount:,} ل.س\n"
            f"💸 عمولة الخدمة: {fee:,} ل.س\n"
            f"💳 المجموع: {total:,} ل.س\n"
        )
        add_pending_request(
            user_id=user_id,
            username=call.from_user.username,
            request_text=admin_msg
        )
        bot.send_message(
            user_id,
            "✅ تم إرسال طلبك للإدارة. سيتم معالجة طلبك خلال 1 إلى 4 دقائق."
        )
        user_states.pop(user_id, None)

    # ================= منطق الإلغاء العام ==================
    @bot.callback_query_handler(func=lambda call: call.data == "cancel_all")
    def cancel_all(call):
        user_id = call.from_user.id
        bot.send_message(call.message.chat.id, "❌ تم إلغاء العملية.")
        user_states.pop(user_id, None)

    # ============= منطق الرجوع للقائمة السابقة =============
    @bot.message_handler(func=lambda msg: msg.text == "⬅️ رجوع")
    def go_back(msg):
        user_id = msg.from_user.id
        user_states.pop(user_id, None)
        # يمكنك وضع هنا قائمة رئيسية للعميل
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("🔋 شحن وحدات سيرياتيل", "🔋 شحن وحدات MTN")
        markup.add("💳 دفع فاتورة سيرياتيل", "💳 دفع فاتورة MTN")
        markup.add("💡 دفع فاتورة كهرباء", "🚰 دفع فاتورة ماء")
        bot.send_message(msg.chat.id, "تم الرجوع للقائمة الرئيسية.", reply_markup=markup)
