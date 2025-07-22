# services/queue_service.py
import time
from database.db import get_table
from config import ADMIN_MAIN_ID
from telebot import types


def delete_pending_request(request_id: int) -> None:
    """
    يحذف صفّ الطلب ذي الـ id المحدد من جدول pending_requests
    """
    get_table("pending_requests") \
        .delete() \
        .eq("id", request_id) \
        .execute()


def process_queue(bot):
    """
    خدمة الطابور: ترسل للأدمن طلبًا واحدًا فقط في كل مرة مع أزرار للموافقة أو الرفض،
    ثم تنتظر دقيقتين قبل الطلب التالي.
    """
    while True:
        # 1) جلب أقدم طلب بالحالة pending
        response = (
            get_table("pending_requests")
            .select("*")
            .eq("status", "pending")
            .order("created_at")
            .limit(1)
            .execute()
        )
        data = response.data

        if not data:
            # لا يوجد طلبات حالياً ‑ انتظر ثم أعد المحاولة
            time.sleep(3)
            continue

        req = data[0]
        request_id = req["id"]
        user_id = req["user_id"]

        # 2) تجهيز الزرّين للموافقة أو الرفض
        admin_keyboard = types.InlineKeyboardMarkup(row_width=2)
        admin_keyboard.add(
            types.InlineKeyboardButton(
                "✅ قبول الطلب", callback_data=f"admin_approve_{request_id}"
            ),
            types.InlineKeyboardButton(
                "❌ رفض الطلب", callback_data=f"admin_reject_{request_id}"
            )
        )

        # 3) أرسل الطلب للأدمن مع الأزرار
        msg = (
            f"🆕 طلب جديد من @{req.get('username','')} (ID: {user_id}):\n"
            f"{req['request_text']}\n"
            f"رقم الطلب: {request_id}\n"
            f"الرد عبر الأزرار أدناه:"
        )
        bot.send_message(ADMIN_MAIN_ID, msg, reply_markup=admin_keyboard)

        # 4) حدّث الحالة إلى processing ليمنع الإرسال المزدوج
        get_table("pending_requests") \
            .update({"status": "processing"}) \
            .eq("id", request_id) \
            .execute()

        # 5) انتظر دقيقتين قبل الطلب التالي
        time.sleep(120)


def add_pending_request(user_id: int, username: str | None, request_text: str) -> None:
    """
    حفظ الطلب في قاعدة البيانات فور استلامه من العميل (دون تحديث المحفظة).
    """
    get_table("pending_requests").insert({
        "user_id": user_id,
        "username": (username or ""),
        "request_text": request_text,
        "status": "pending",
    }).execute()

# ==================================================================
# === مثال handlers لتعليق الأدمن وإرسال نص أو صورة للعميل ===
# ==================================================================

# أدناه مثال على handlers يجب وضعه في ملف handlers (products.py مثلاً)
# لمعالجة زر الموافقة وإرسال رسالة/صورة للعميل:

@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_approve_"))
def handle_admin_approve(call):
    # استخراج request_id من callback data
    _, _, request_id = call.data.split("_")
    request_id = int(request_id)
    # جلب بيانات الطلب من جدول pending_requests
    res = get_table("pending_requests").select("user_id,request_text").eq("id", request_id).execute()
    if not res.data:
        bot.answer_callback_query(call.id, "❌ الطلب غير موجود أو مُعالج بالفعل.")
        return
    req = res.data[0]
    user_id = req["user_id"]

    # مثال: إرسال رسالة نصيّة
    bot.send_message(user_id, f"✅ طلبك رقم {request_id} تمت الموافقة عليه!
{req['request_text']}")

    # مثال: إرسال صورة (استبدل 'FILE_ID' بمعرّف الصورة الفعلي أو مسار)
    # bot.send_photo(user_id, photo="FILE_ID", caption="هنا صورة تنفيذ الطلب")

    # حذف الطلب من القاعدة بعد الرد
    delete_pending_request(request_id)
    bot.answer_callback_query(call.id, "تمت معالجة الطلب وحُذف من قائمة الانتظار.")
