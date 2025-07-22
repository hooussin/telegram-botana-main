# handlers/admin.py

from datetime import datetime
import logging
import json
import os
import re

from telebot import types
from config import ADMINS, ADMIN_MAIN_ID
from database.db import get_table
from services.wallet_service import (
    register_user_if_not_exist,
    get_all_products, get_product_by_id, get_balance, add_balance,
    get_purchases, get_deposit_transfers
)
from services.cleanup_service import delete_inactive_users
from services.recharge_service import validate_recharge_code
from services.queue_service import add_pending_request, delete_pending_request

# ============= مسح الطلب المعلق من قائمة الانتظار الداخلية =============
def clear_pending_request(user_id):
    try:
        from handlers.recharge import recharge_pending
        recharge_pending.discard(user_id)
    except Exception:
        pass
# ======================================================================

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

def register(bot, history):
    # ========== هاندلرات إدارة الطابور ==========
    @bot.message_handler(func=lambda msg: msg.text and re.match(r'/done_(\d+)', msg.text))
    def handle_done(msg):
        req_id = int(re.match(r'/done_(\d+)', msg.text).group(1))
        delete_pending_request(req_id)
        bot.reply_to(msg, f"✅ تم إنهاء الطلب رقم {req_id}")

    @bot.message_handler(func=lambda msg: msg.text and re.match(r'/cancel_(\d+)', msg.text))
    def handle_cancel(msg):
        req_id = int(re.match(r'/cancel_(\d+)', msg.text).group(1))
        delete_pending_request(req_id)
        bot.reply_to(msg, f"🚫 تم إلغاء الطلب رقم {req_id}")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("admin_approve_"))
    def handle_admin_approve_queue(call):
        # 1) استخرج المعرف
        request_id = int(call.data.split("_")[-1])
        # 2) جلب بيانات الطلب
        res = get_table("pending_requests") \
              .select("user_id,request_text") \
              .eq("id", request_id) \
              .execute()
        if not res.data:
            bot.answer_callback_query(call.id, "❌ الطلب غير موجود أو مُعالج بالفعل.")
            return
        req = res.data[0]
        user_id = req["user_id"]

        # 3) أرسل رسالة نصّية أو صورة للعميل
        bot.send_message(
            user_id,
            f"✅ طلبك رقم {request_id} تمت الموافقة عليه!\n{req['request_text']}"
        )
        # مثال لإرسال صورة:
        # bot.send_photo(user_id, photo="FILE_ID", caption="تم تنفيذ طلبك بالصورة المرفقة.")

        # 4) حذف الطلب من قاعدة البيانات
        delete_pending_request(request_id)

        # 5) إعلام الأدمن وإزالة الأزرار
        bot.answer_callback_query(call.id, "✅ تمت الموافقة وحُذف الطلب.")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("admin_reject_"))
    def handle_admin_reject_queue(call):
        request_id = int(call.data.split("_")[-1])
        # جلب user_id فقط
        res = get_table("pending_requests") \
              .select("user_id") \
              .eq("id", request_id) \
              .execute()
        if not res.data:
            bot.answer_callback_query(call.id, "❌ الطلب غير موجود أو مُعالج بالفعل.")
            return
        user_id = res.data[0]["user_id"]

        # إرسال رسالة رفض للعميل
        bot.send_message(
            user_id,
            f"❌ طلبك رقم {request_id} تم رفضه. يمكنك المحاولة مرة أخرى لاحقًا."
        )

        # حذف الطلب من قاعدة البيانات
        delete_pending_request(request_id)

        bot.answer_callback_query(call.id, "❌ تم رفض الطلب وحُذف من الطابور.")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    # ==========================================

    # ---------- تأكيد/رفض شحن المحفظة عبر أكواد وكلاء ----------
    @bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_add_"))
    def confirm_wallet_add(call):
        try:
            _, _, user_id_str, amount_str = call.data.split("_")
            user_id = int(user_id_str)
            amount = int(float(amount_str))
            register_user_if_not_exist(user_id)
            add_balance(user_id, amount)
            get_table("pending_requests") \
                .update({"status": "done"}) \
                .eq("id", call.message.message_id) \
                .execute()
            clear_pending_request(user_id)
            bot.send_message(user_id, f"✅ تم إضافة {amount:,} ل.س إلى محفظتك بنجاح.")
            bot.answer_callback_query(call.id, "✅ تمت الموافقة")
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            bot.send_message(
                call.message.chat.id,
                f"✅ تم تأكيد العملية ورقمُه `{call.message.message_id}`",
                parse_mode="Markdown",
            )
        except Exception as e:
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
        bot.send_message(
            user_id,
            f"❌ تم رفض عملية الشحن.\n📝 السبب: {reason}"
        )
        bot.answer_callback_query(call.id, "❌ تم رفض العملية")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        get_table("pending_requests") \
            .update({"status": "cancelled"}) \
            .eq("id", call.message.message_id) \
            .execute()
        clear_pending_request(user_id)


    # ---------- تقرير الأكواد السرية ----------
    @bot.message_handler(commands=["تقرير_الوكلاء"])
    def generate_report(msg):
        if msg.from_user.id not in ADMINS:
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

    # ---------- واجهة وكلائنا ----------
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
            bot.send_message(msg.chat.id, "❌ الرجاء إدخال مبلغ صالح.")
            return
        user_str = f"{msg.from_user.first_name} (@{msg.from_user.username or 'بدون_معرف'})"
        user_id = msg.from_user.id
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        ops_data = load_code_operations()
        ops_data.setdefault(code, []).append({"user": user_str, "user_id": user_id, "amount": amount, "date": now})
        save_code_operations(ops_data)
        register_user_if_not_exist(user_id)
        add_balance(user_id, amount)
        bot.send_message(msg.chat.id, f"✅ تم تحويل {amount:,} ل.س إلى محفظتك عبر وكيل.")
        admin_msg = f"✅ شحن {amount:,} ل.س للمستخدم `{user_id}` عبر كود `{code}`"
        add_pending_request(user_id, msg.from_user.username, admin_msg)
