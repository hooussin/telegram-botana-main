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
        # التأكد: هل هناك طلب قيد التنفيذ للأدمن؟
        processing = (
            get_table("pending_requests")
            .select("*")
            .eq("status", "processing")
            .execute()
        ).data

        if processing:
            # يوجد طلب قيد التنفيذ - انتظر قليلًا ثم أعد المحاولة
            time.sleep(3)
            continue

        # إذا لا يوجد طلب قيد التنفيذ، جلب أقدم طلب معلق
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
            # حدّث الحالة إلى "processing"
            get_table("pending_requests").update({"status": "processing"}).eq("id", req['id']).execute()
            # أرسل الطلب للأدمن
            msg = (
                f"🆕 طلب جديد من @{req.get('username','')} (ID: {req['user_id']}):\n"
                f"{req['request_text']}\n"
                f"رقم الطلب: {req['id']}\n"
                f"الرد بـ /done_{req['id']} عند التنفيذ أو /cancel_{req['id']} للإلغاء."
            )
            bot.send_message(ADMIN_MAIN_ID, msg)
            # انتظر قليلاً ثم أعد المحاولة (حتى لا ترسل نفس الطلب مرتين إذا حدث تأخير بالشبكة)
            time.sleep(2)
        else:
            # إذا لا يوجد طلبات، انتظر ثم تحقق مجددًا
            time.sleep(3)

def add_pending_request(user_id, username, request_text):
    """
    حفظ الطلب في قاعدة البيانات فور وصوله من العميل.
    """
    table = get_table("pending_requests")
    table.insert({
        "user_id": user_id,
        "username": username,
        "request_text": request_text,
    }).execute()
