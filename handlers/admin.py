# handlers/admin.py

import logging
import json
import os
import re
from datetime import datetime

from telebot import types

from config import ADMINS, ADMIN_MAIN_ID
from database.db import get_table
from services.wallet_service import (
    register_user_if_not_exist,
    deduct_balance,
    add_purchase,
    add_balance
)
from services.queue_service import add_pending_request, delete_pending_request, process_queue
from services.cleanup_service import delete_inactive_users
from services.recharge_service import validate_recharge_code

# ملف الأكواد السرية
SECRET_CODES_FILE = "data/secret_codes.json"
os.makedirs("data", exist_ok=True)
if not os.path.isfile(SECRET_CODES_FILE):
    with open(SECRET_CODES_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f)


def load_code_operations():
    with open(SECRET_CODES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_code_operations(data):
    with open(SECRET_CODES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


VALID_SECRET_CODES = [
    "363836369", "36313251", "646460923",
    "91914096", "78708501", "06580193"
]


def clear_pending_request(user_id):
    try:
        from handlers.recharge import recharge_pending
        recharge_pending.discard(user_id)
    except Exception:
        pass


def register(bot, history):
    # ========== أوامر /done و /cancel ==========
    @bot.message_handler(func=lambda msg: msg.text and re.match(r'/done_(\d+)', msg.text))
    def handle_done(msg):
        req_id = int(re.match(r'/done_(\d+)', msg.text).group(1))
        delete_pending_request(req_id)
        bot.reply_to(msg, f"✅ تم إنهاء الطلب {req_id}")

    @bot.message_handler(func=lambda msg: msg.text and re.match(r'/cancel_(\d+)', msg.text))
    def handle_cancel(msg):
        req_id = int(re.match(r'/cancel_(\d+)', msg.text).group(1))
        delete_pending_request(req_id)
        bot.reply_to(msg, f"🚫 تم إلغاء الطلب {req_id}")

    # ========== معالج الطابور الموحد ==========
    @bot.callback_query_handler(func=lambda call: call.data.startswith("admin_queue_"))
    def handle_queue_action(call):
        parts = call.data.split("_")
        action = parts[2]
        request_id = int(parts[3])

        res = get_table("pending_requests") \
            .select("user_id", "request_text") \
            .eq("id", request_id) \
            .execute()
        if not res.data:
            return bot.answer_callback_query(call.id, "❌ الطلب غير موجود.")
        req = res.data[0]
        user_id = req["user_id"]
        text = req["request_text"]

        bot.delete_message(call.message.chat.id, call.message.message_id)

        if action == "postpone":
            delete_pending_request(request_id)
            add_pending_request(user_id, None, text)
            bot.answer_callback_query(call.id, "✅ تم تأجيل الطلب.")
            bot.send_message(
                user_id,
                "⏳ تم تأجيل طلبك بسبب الضغط، سيتم معالجته خلال 5–10 دقائق."
            )
        else:
            m_price = re.search(r"💵 السعر: ([\d,]+) ل\.س", text)
            price = int(m_price.group(1).replace(",", "")) if m_price else 0
            m_prod = re.search(r"🔖 منتج: (.+)", text)
            product_name = m_prod.group(1) if m_prod else ""

            deduct_balance(user_id, price)
            add_purchase(user_id, product_name, price)
            delete_pending_request(request_id)
            bot.answer_callback_query(call.id, "✅ تم قبول وتنفيذ الطلب.")
            bot.send_message(
                user_id,
                f"✅ تم تنفيذ طلبك: {product_name}.\n"
                f"وخصم {price:,} ل.س من محفظتك."
            )

        process_queue(bot)

    # ========== شحن المحفظة وتقرير الأكواد وغيرها ==========
    @bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_add_"))
    def confirm_wallet_add(call):
        _, _, user_id_str, amount_str = call.data.split("_")
        user_id = int(user_id_str)
        amount = int(float(amount_str))
        register_user_if_not_exist(user_id)
        add_balance(user_id, amount)
        clear_pending_request(user_id)
        bot.send_message(user_id, f"✅ تم إضافة {amount:,} ل.س إلى محفظتك بنجاح.")
        bot.answer_callback_query(call.id, "✅ تمت الموافقة")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("reject_add_"))
    def reject_wallet_add(call):
        user_id = int(call.data.split("_")[-1])
        bot.send_message(call.message.chat.id, "📝 اكتب سبب الرفض:")
        bot.register_next_step_handler_by_chat_id(
            call.message.chat.id,
            lambda m: process_rejection(m, user_id, call),
        )

    def process_rejection(msg, user_id, call):
        reason = msg.text.strip()
        bot.send_message(
            user_id,
            f"❌ تم رفض عملية الشحن.\n📝 السبب: {reason}"
        )
        bot.answer_callback_query(call.id, "❌ تم رفض العملية")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        clear_pending_request(user_id)

    @bot.message_handler(commands=["تقرير_الوكلاء"])
    def generate_report(msg):
        if msg.from_user.id not in ADMINS:
            return
        data = load_code_operations()
        if not data:
            bot.send_message(msg.chat.id, "📭 لا توجد أي عمليات عبر الأكواد.")
            return
        report = "📊 تقرير عمليات الأكواد:\n"
        for code, ops in data.items():
            report += f"\n🔐 الكود: `{code}`\n"
            for entry in ops:
                report += f"▪️ {entry['amount']:,} ل.س | {entry['date']} | {entry['user']}\n"
        bot.send_message(msg.chat.id, report, parse_mode="Markdown")

    @bot.message_handler(func=lambda m: m.text == "🏪 وكلائنا")
    def handle_agents_entry(msg):
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("⬅️ رجوع", "✅ متابعة")
        bot.send_message(
            msg.chat.id,
            "🏪 وكلاؤنا:\n\n"
            "📍 دمشق - ريف دمشق – قدسيا – صالة الببجي الاحترافية - 090000000\n"
            "📍 دمشق - الزاهرة الجديدة – محل الورد - 09111111\n"
            "📍 قدسيا – الساحة - 092000000\n\n"
            "✅ اضغط (متابعة) إذا كنت تملك كودًا سريًا من وكيل.",
            reply_markup=kb,
        )

    @bot.message_handler(func=lambda m: m.text == "✅ متابعة")
    def ask_for_secret_code(msg):
        bot.send_message(msg.chat.id, "🔐 أدخل الكود السري:")
        bot.register_next_step_handler(msg, verify_code)

    def verify_code(msg):
        code = msg.text.strip()
        if code not in VALID_SECRET_CODES:
            bot.send_message(msg.chat.id, "❌ كود غير صحيح.")
            return
        bot.send_message(msg.chat.id, "💰 أدخل المبلغ:")
        bot.register_next_step_handler(msg, lambda m: confirm_amount(m, code))

    def confirm_amount(msg, code):
        amount = int(msg.text.strip())
        user_id = msg.from_user.id
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        ops = load_code_operations()
        ops.setdefault(code, []).append({"user": msg.from_user.first_name, "amount": amount, "date": now})
        save_code_operations(ops)
        register_user_if_not_exist(user_id)
        add_balance(user_id, amount)
        bot.send_message(msg.chat.id, f"✅ تم تحويل {amount:,} ل.س إلى محفظتك.")
        admin_msg = f"✅ شحن {amount:,} ل.س للمستخدم `{user_id}` عبر كود `{code}`"
        add_pending_request(user_id, msg.from_user.username, admin_msg)
        process_queue(bot)

# نهاية handlers/admin.py
