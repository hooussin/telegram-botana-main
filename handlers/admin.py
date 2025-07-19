from telebot import types
from datetime import datetime
from config import ADMINS, ADMIN_MAIN_ID
from services.wallet_service import (
    get_all_products, get_product_by_id, get_balance, get_purchases, get_deposit_transfers
)
from services.cleanup_service import delete_inactive_users
from services.recharge_service import validate_recharge_code
import logging
import json
import os
import re
from database.db import get_table

# ============= إضافة لمسح الطلب المعلق للعميل =============
def clear_pending_request(user_id):
    try:
        from handlers.recharge import recharge_pending
        recharge_pending.discard(user_id)
    except Exception:
        pass
# =========================================================

# ========== دعم الطوابير ==========
@bot.message_handler(func=lambda msg: msg.text and re.match(r'/done_(\d+)', msg.text))
def handle_done(msg):
    req_id = int(re.match(r'/done_(\d+)', msg.text).group(1))
    get_table("pending_requests").update({"status": "done"}).eq("id", req_id).execute()
    bot.reply_to(msg, f"✅ تم إنهاء الطلب رقم {req_id}")

@bot.message_handler(func=lambda msg: msg.text and re.match(r'/cancel_(\d+)', msg.text))
def handle_cancel(msg):
    req_id = int(re.match(r'/cancel_(\d+)', msg.text).group(1))
    get_table("pending_requests").update({"status": "cancelled"}).eq("id", req_id).execute()
    bot.reply_to(msg, f"🚫 تم إلغاء الطلب رقم {req_id}")
# ================================

# ملف تخزين عمليات الأكواد السرّية
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

# قائمة الأكواد المعتمَدة من الوكلاء
VALID_SECRET_CODES = [
    "363836369", "36313251", "646460923",
    "91914096", "78708501", "06580193"
]

def register(bot, history):

    # ---------- معالجة أزرار تأكيد/رفض الشحن ----------
    @bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_add_"))
    def confirm_wallet_add(call):
        try:
            _, _, user_id_str, amount_str = call.data.split("_")
            user_id = int(user_id_str)
            amount = int(float(amount_str))

            register_user_if_not_exist(user_id)
            add_balance(user_id, amount)

            # 🟢 حذف الطلب المعلق من قائمة المعلقين بعد التنفيذ
            clear_pending_request(user_id)

            bot.send_message(user_id, f"✅ تم إضافة {amount:,} ل.س إلى محفظتك بنجاح.")
            bot.answer_callback_query(call.id, "✅ تمت الموافقة")
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            bot.send_message(
                call.message.chat.id,
                f"✅ تم تأكيد العملية وإضافة الرصيد للمستخدم `{user_id}`",
                parse_mode="Markdown",
            )
        except Exception as e:
            # تسجيل Traceback كامل في سجلّ Render
            logging.exception("❌ خطأ داخل confirm_wallet_add:")
            bot.send_message(call.message.chat.id, f"❌ حدث خطأ: {e}")

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
        bot.send_message(user_id, f"❌ تم رفض عملية الشحن.\n📝 السبب: {reason}")
        bot.answer_callback_query(call.id, "❌ تم رفض العملية")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        # 🟢 حذف الطلب المعلق بعد الرفض
        clear_pending_request(user_id)

    # ---------- تقرير الأكواد السرّية ----------
    @bot.message_handler(commands=["تقرير_الوكلاء"])
    def generate_report(msg):
        if msg.from_user.id != ADMIN_MAIN_ID:
            return

        data = load_code_operations()
        if not data:
            bot.send_message(msg.chat.id, "📭 لا توجد أي عمليات تحويل عبر الأكواد بعد.")
            return

        report = "📊 تقرير عمليات الأكواد:\n"
        for code, ops in data.items():
            report += f"\n🔐 الكود: `{code}`\n"
            for entry in ops:
                report += f"▪️ {entry['amount']:,} ل.س | {entry['date']} | {entry['user']}\n"
        bot.send_message(msg.chat.id, report, parse_mode="Markdown")

    # ---------- واجهة الوكلاء ----------
    @bot.message_handler(func=lambda m: m.text == "🏪 وكلائنا")
    def handle_agents_entry(msg):
        history.setdefault(msg.from_user.id, []).append("agents_page")
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("⬅️ رجوع", "✅ متابعة")
        bot.send_message(
            msg.chat.id,
            "🏪 وكلاؤنا:\n\n"
            "📍 دمشق - ريف دمشق – قدسيا – صالة الببجي الاحترافية - 090000000\n"
            "📍 دمشق - الزاهرة الجديدة – محل الورد - 09111111\n"
            "📍 قدسيا – الساحة - 092000000\n"
            "📍 يعفور – محل الايهم - 093000000\n"
            "📍 قدسيا – الاحداث – موبيلاتي - 096000000\n\n"
            "✅ اضغط (متابعة) إذا كنت تملك كودًا سريًا من وكيل لإضافة رصيد لمحفظتك.",
            reply_markup=kb,
        )

    @bot.message_handler(func=lambda m: m.text == "✅ متابعة")
    def ask_for_secret_code(msg):
        history.setdefault(msg.from_user.id, []).append("enter_secret_code")
        bot.send_message(msg.chat.id, "🔐 أدخل الكود السري (لن يظهر في المحادثة):")
        bot.register_next_step_handler(msg, verify_code)

    # ---------- التحقق من الكود وإتمام التحويل ----------
    def verify_code(msg):
        code = msg.text.strip()
        if code not in VALID_SECRET_CODES:
            bot.send_message(msg.chat.id, "❌ كود غير صحيح أو غير معتمد.")
            return
        bot.send_message(msg.chat.id, "💰 أدخل المبلغ الذي تريد تحويله للمحفظة:")
        bot.register_next_step_handler(msg, lambda m: confirm_amount(m, code))

    def confirm_amount(msg, code):
        try:
            amount = int(msg.text.strip())
        except ValueError:
            bot.send_message(msg.chat.id, "❌ الرجاء إدخال مبلغ صحيح.")
            return

        user_str = f"{msg.from_user.first_name} (@{msg.from_user.username or 'بدون_معرف'})"
        user_id = msg.from_user.id
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        data = load_code_operations()
        data.setdefault(code, []).append(
            {"user": user_str, "user_id": user_id, "amount": amount, "date": now}
        )
        save_code_operations(data)

        register_user_if_not_exist(user_id)
        add_balance(user_id, amount)

        bot.send_message(msg.chat.id, f"✅ تم تحويل {amount:,} ل.س إلى محفظتك عبر وكيل.")
        bot.send_message(
            ADMIN_MAIN_ID,
            f"✅ تم شحن {amount:,} ل.س للمستخدم `{user_id}` عبر كود `{code}`",
            parse_mode="Markdown",
        )
