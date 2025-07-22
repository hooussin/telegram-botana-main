# services/queue_service.py

import time
import logging
from datetime import datetime
import httpx

from database.db import client
from config import ADMIN_MAIN_ID
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# اسم جدول الانتظار في Supabase
QUEUE_TABLE = "pending_requests"


def add_pending_request(user_id: int, username: str, request_text: str):
    """
    إضافة طلب جديد إلى نهاية قائمة الانتظار.
    يحاول 3 مرات عند فشل الاتصال.
    """
    for attempt in range(1, 4):
        try:
            client.table(QUEUE_TABLE).insert({
                "user_id": user_id,
                "username": username,
                "request_text": request_text,
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            return
        except httpx.ReadError as e:
            logging.warning(f"Attempt {attempt}: ReadError in add_pending_request: {e}")
            time.sleep(0.5)
    logging.error(f"Failed to add pending request for user {user_id} after 3 attempts.")


def delete_pending_request(request_id: int):
    """
    حذف الطلب بالكامل من قائمة الانتظار.
    """
    try:
        client.table(QUEUE_TABLE).delete().eq("id", request_id).execute()
    except Exception:
        logging.exception(f"Error deleting pending request {request_id}")


def get_next_request():
    """
    جلب أقدم طلب متاح (أول مدخل حسب created_at).
    Returns the record dict or None.
    """
    try:
        res = (
            client.table(QUEUE_TABLE)
            .select("*")
            .order("created_at")
            .limit(1)
            .execute()
        )
        data = res.data or []
        return data[0] if data else None
    except httpx.ReadError as e:
        logging.warning(f"ReadError in get_next_request: {e}")
        return None
    except Exception:
        logging.exception("Unexpected error in get_next_request")
        return None


def update_request_admin_message_id(request_id: int, message_id: int):
    """
    دالة وهمية لأن العمود admin_message_id غير موجود في الجدول.
    فقط تسجل المحاولة ولا تفعل شيئًا.
    """
    logging.debug(f"Skipping update_request_admin_message_id for request {request_id}")


def postpone_request(request_id: int):
    """
    تأجيل الطلب: نعيد ضبط created_at للوقت الحالي
    ليعود الطلب إلى نهاية الطابور.
    """
    try:
        now = datetime.utcnow().isoformat()
        client.table(QUEUE_TABLE) \
            .update({"created_at": now}) \
            .eq("id", request_id) \
            .execute()
    except Exception:
        logging.exception(f"Error postponing request {request_id}")


def process_queue(bot):
    """
    عرض للمدير (ADMIN_MAIN_ID) الطلب التالي في قائمة الانتظار،
    ويرفق مع الرسالة زرين: 🔁 تأجيل و✅ قبول.
    يجب استدعاء هذا بعد إضافة طلب جديد أو عند الانتهاء من معاملة سابقة.
    أي استثناء يُسجّل ولا يوقف الخيط.
    """
    try:
        req = get_next_request()
        if not req:
            return

        request_id = req.get("id")
        text = req.get("request_text", "")

        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("🔁 تأجيل", callback_data=f"admin_queue_postpone_{request_id}"),
            InlineKeyboardButton("✅ قبول",  callback_data=f"admin_queue_accept_{request_id}")
        )

        bot.send_message(ADMIN_MAIN_ID, text, reply_markup=keyboard)
    except Exception:
        logging.exception("Error in process_queue, continuing...")
