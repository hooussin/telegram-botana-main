# services/queue_service.py

import time
from datetime import datetime

from database.db import client
from config import ADMIN_MAIN_ID
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# اسم جدول الانتظار في Supabase
QUEUE_TABLE = "pending_requests"


def add_pending_request(user_id: int, username: str, request_text: str):
    """
    إضافة طلب جديد إلى نهاية قائمة الانتظار.
    """
    client.table(QUEUE_TABLE).insert({
        "user_id": user_id,
        "username": username,
        "request_text": request_text,
        "created_at": datetime.utcnow().isoformat()
    }).execute()


def delete_pending_request(request_id: int):
    """
    حذف الطلب بالكامل من قائمة الانتظار.
    """
    client.table(QUEUE_TABLE).delete().eq("id", request_id).execute()


def get_next_request():
    """
    جلب أقدم طلب متاح (أول مدخل حسب created_at).
    Returns the record dict or None.
    """
    res = (
        client.table(QUEUE_TABLE)
        .select("*")
        .order("created_at", ascending=True)   # هنا مرر ascending كوسيط مسمّى
        .limit(1)
        .execute()
    )
    data = res.data or []
    return data[0] if data else None


def update_request_admin_message_id(request_id: int, message_id: int):
    """
    تخزين معرف رسالة الأدمن المسؤولة عن هذا الطلب،
    حتى نتمكّن من حذفها لاحقًا عند التأجيل أو القبول.
    """
    client.table(QUEUE_TABLE) \
        .update({"admin_message_id": message_id}) \
        .eq("id", request_id) \
        .execute()


def postpone_request(request_id: int):
    """
    تأجيل الطلب: نعيد ضبط created_at للوقت الحالي
    ليعود الطلب إلى نهاية الطابور.
    """
    now = datetime.utcnow().isoformat()
    client.table(QUEUE_TABLE) \
        .update({"created_at": now}) \
        .eq("id", request_id) \
        .execute()


def process_queue(bot):
    """
    عرض للمدير (ADMIN_MAIN_ID) الطلب التالي في قائمة الانتظار،
    ويرفق مع الرسالة زرين: 🔁 تأجيل و✅ قبول.
    يجب استدعاء هذا بعد إضافة طلب جديد أو عند الانتهاء من معاملة سابقة.
    """
    req = get_next_request()
    if not req:
        return

    request_id = req["id"]
    text = req["request_text"]

    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("🔁 تأجيل", callback_data=f"admin_reject_{request_id}"),
        InlineKeyboardButton("✅ قبول",  callback_data=f"admin_approve_{request_id}")
    )

    msg = bot.send_message(ADMIN_MAIN_ID, text, reply_markup=keyboard)
    update_request_admin_message_id(request_id, msg.message_id)
