# services/queue_service.py
import time
from database.db import get_table
from config import ADMIN_MAIN_ID


def process_queue(bot):
    """
    خدمة الطابور: ترسل للأدمن طلبًا واحدًا فقط في كل مرة.
    إذا أنهى الأدمن الطلب (done/cancel)، ينتقل فورًا للطلب التالي.
    """
    while True:
        # 1) هل يوجد طلب قيد التنفيذ؟
        processing = (
            get_table("pending_requests")
            .select("*")
            .eq("status", "processing")
            .execute()
        ).data

        if processing:
            # يوجد طلب قيد التنفيذ ‑ انتظر قليلاً ثم تحقق مجددًا
            time.sleep(3)
            continue

        # 2) إذا لا يوجد، جلب أقدم طلب بالحالة pending
        response = (
            get_table("pending_requests")
            .select("*")
            .eq("status", "pending")
            .order("created_at")
            .limit(1)
            .execute()
        )
        data = response.data

        if data:
            req = data[0]

            # حدِّث الحالة إلى processing
            (
                get_table("pending_requests")
                .update({"status": "processing"})
                .eq("id", req["id"])
                .execute()
            )

            # أرسل الطلب للأدمن
            msg = (
                f"🆕 طلب جديد من @{req.get('username','')} (ID: {req['user_id']}):\n"
                f"{req['request_text']}\n"
                f"رقم الطلب: {req['id']}\n"
                f"الرد بـ /done_{req['id']} عند التنفيذ أو /cancel_{req['id']} للإلغاء."
            )
            bot.send_message(ADMIN_MAIN_ID, msg)

            # تأخير بسيط لمنع التكرار إذا حدث lag
            time.sleep(2)
        else:
            # لا يوجد طلبات حالياً ‑ انتظر ثم أعد المحاولة
            time.sleep(3)


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
        "status": "pending",           # ← السطر المهم لإدارة حالة الطابور
    }).execute()
