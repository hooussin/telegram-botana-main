# queue_service.py
from datetime import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from db import get_next_request, update_request_admin_message_id, postpone_request

# معرّف شات الأدمن
ADMIN_CHAT_ID = 6935846121  # عدّله إلى معرّف الأدمن الحقيقي

def enqueue_request(bot, request):
    """
    يُستدعى هذا عند تأكيد العميل لشراء منتج ويضاف الطلب إلى قاعدة البيانات.
    ثم يُشير للمعالجة الفورية أو الانتظار في الطابور.
    """
    # حفظ الطلب في قاعدة البيانات (نفترض أن الدالة تقوم بذلك)
    save_request(request)

    # إخطار العميل بوضع الطلب في الانتظار
    bot.send_message(request.chat_id, "✅ طلبك الآن قيد الانتظار. شكرًا لصبرك.")

    # محاولة معالجة الطلبات إذا لم يكن هناك معالجة حالية
    process_queue(bot)


def process_queue(bot):
    """
    يعرض للمدير الطلب التالي في الطابور مع معلومات المنتج وأزرار تأجيل/قبول.
    """
    # جلب الطلب التالي بناءً على وقت الإنشاء
    request = get_next_request()
    if not request:
        return

    info = request.product_info  # dict يحتوي على name, quantity, total_price
    text = (
        f"🆕 طلب جديد في الطابور:\n"
        f"العميل: @{request.username}\n"
        f"المنتج: {info['name']}\n"
        f"الكمية: {info['quantity']}\n"
        f"السعر الإجمالي: {info['total_price']} ل.س"
    )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔁 تأجيل", callback_data=f"postpone_{request.id}"),
        InlineKeyboardButton("✅ قبول", callback_data=f"approve_{request.id}")
    ]])

    msg = bot.send_message(ADMIN_CHAT_ID, text, reply_markup=keyboard)

    # حفظ رقم رسالة الأدمن لتمكين حذفها لاحقًا
    update_request_admin_message_id(request.id, msg.message_id)


# admin.py
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackQueryHandler, MessageHandler, Filters
from db import (
    get_request,
    postpone_request,
    delete_request,
    deduct_balance,
    update_request_admin_detail_message_id
)

# تعريف شات الأدمن نفسه
ADMIN_CHAT_ID = 123456789  # عدّله


def handle_postpone(update, context):
    query = update.callback_query
    request_id = int(query.data.split("_")[1])

    # حذف رسالة الطابور من عند الأدمن
    context.bot.delete_message(chat_id=query.message.chat.id, message_id=query.message.message_id)

    # إعادة إرسال الطلب إلى نهاية الطابور
    postpone_request(request_id)

    # إخطار الأدمن
    context.bot.send_message(ADMIN_CHAT_ID, "✅ تم تأجيل الدور بنجاح.")

    # إخطار العميل
    req = get_request(request_id)
    context.bot.send_message(req.chat_id, "⏳ تم تأجيل طلبك بسبب الضغط، سيتم معالجته خلال 5–10 دقائق.")

    # عرض الطلب التالي
    from queue_service import process_queue
    process_queue(context.bot)


def handle_approve(update, context):
    query = update.callback_query
    request_id = int(query.data.split("_")[1])

    # حذف رسالة الطابور من عند الأدمن
    context.bot.delete_message(chat_id=query.message.chat.id, message_id=query.message.message_id)

    # جلب تفاصيل الطلب
    req = get_request(request_id)
    info = req.product_info
    text = (
        f"📦 تفاصيل طلب العميل @{req.username}:\n"
        f"المنتج: {info['name']}\n"
        f"الكمية: {info['quantity']}\n"
        f"السعر الإجمالي: {info['total_price']} ل.س"
    )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_{request_id}"),
        InlineKeyboardButton("✅ تأكيد", callback_data=f"confirm_{request_id}")
    ]])

    msg = context.bot.send_message(ADMIN_CHAT_ID, text, reply_markup=keyboard)

    # حفظ معرف رسالة تفاصيل الأدمن للتمكين من إرسال رسائل لاحقة للعميل
    update_request_admin_detail_message_id(request_id, msg.message_id)


def handle_confirm(update, context):
    query = update.callback_query
    request_id = int(query.data.split("_")[1])

    req = get_request(request_id)

    # خصم المبلغ من المحفظة
    deduct_balance(req.user_id, req.product_info['total_price'])

    # إزالة الطلب من قاعدة البيانات
    delete_request(request_id)

    # إخطار العميل بنجاح التنفيذ
    context.bot.send_message(
        req.chat_id,
        f"✅ تم تنفيذ طلبك: {req.product_info['name']} x {req.product_info['quantity']}، وتم خصم {req.product_info['total_price']} ل.س من محفظتك."
    )

    # معالجة الطلب التالي
    from queue_service import process_queue
    process_queue(context.bot)


def handle_cancel(update, context):
    query = update.callback_query
    request_id = int(query.data.split("_")[1])

    req = get_request(request_id)

    # حذف الطلب نهائيًا
    delete_request(request_id)

    # إخطار العميل بالإلغاء
    context.bot.send_message(req.chat_id, "❌ تم إلغاء طلبك.")

    # معالجة الطلب التالي
    from queue_service import process_queue
    process_queue(context.bot)


def setup_dispatcher(dp):
    dp.add_handler(CallbackQueryHandler(handle_postpone, pattern=r'^postpone_'))
    dp.add_handler(CallbackQueryHandler(handle_approve, pattern=r'^approve_'))
    dp.add_handler(CallbackQueryHandler(handle_confirm, pattern=r'^confirm_'))
    dp.add_handler(CallbackQueryHandler(handle_cancel, pattern=r'^cancel_'))
