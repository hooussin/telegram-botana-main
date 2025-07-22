# services/queue_service.py
import time
from database.db import get_table
from config import ADMIN_MAIN_ID


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
    خدمة الطابور: ترسل للأدمن طلبًا واحدًا فقط في كل مرة،
    ثم تحذفه من جدول pending_requests وتنتظر دقيقتين قبل الطلب التالي.
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

        # 2) أرسل الطلب للأدمن
        msg = (
            f"🆕 طلب جديد من @{req.get('username','')} (ID: {req['user_id']}):\n"
            f"{req['request_text']}\n"
            f"رقم الطلب: {request_id}\n"
            f"الرد بـ /done_{request_id} عند التنفيذ أو /cancel_{request_id} للإلغاء."
        )
        bot.send_message(ADMIN_MAIN_ID, msg)

        # 3) حذف السجل من الجدول فورًا بعد الإرسال
        delete_pending_request(request_id)

        # 4) تأخير دقيقتين قبل إرسال الطلب التالي
        time.sleep(120)


def add_pending_request(user_id: int, username: str | None, request_text: str) -> None:
    """
    حفظ الطلب في قاعدة البيانات فور استلامه من العميل.

    Parameters
    ----------
    user_id : int
        آيدي التليجرام للعميل.
    username : str | None
        اسم المستخدم (قد يكون None).
    request_text : str
        نص الطلب الموجَّه للأدمن.
    """
    get_table("pending_requests").insert({
        "user_id": user_id,
        "username": (username or ""),  # تفادي NULL
        "request_text": request_text,
        "status": "pending",
    }).execute()
