# services/queue_service.py
import time
from database.db import get_table
from config import ADMIN_MAIN_ID

def process_queue(bot):
    """
    خدمة تمرّ كل 3 دقائق ترسل طلباً واحداً للأدمن إذا كان في الانتظار.
    الطلبات تظل محفوظة في القاعدة حتى يتعامل معها الأدمن.
    """
    while True:
        # جلب أقدم طلب معلق
        response = (
            get_table("pending_requests")
            .select("*")
            .eq("status", "pending")
            .order("created_at", asc=True)
            .limit(1)
            .execute()
        )
        data = response.data
        if data:
            req = data[0]
            # حدث الحالة إلى "processing"
            get_table("pending_requests").update({"status": "processing"}).eq("id", req['id']).execute()
            # أرسل الطلب للأدمن
            msg = (
                f"🆕 طلب جديد من @{req.get('username','')} (ID: {req['user_id']}):\n"
                f"{req['request_text']}\n"
                f"رقم الطلب: {req['id']}\n"
                f"الرد بـ /done_{req['id']} عند التنفيذ أو /cancel_{req['id']} للإلغاء."
            )
            bot.send_message(ADMIN_MAIN_ID, msg)
            # انتظر 3 دقائق قبل معالجة الطلب التالي
            time.sleep(180)
        else:
            # إذا لا يوجد طلبات، انتظر دقيقة ثم تحقق مجددًا
            time.sleep(60)

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
