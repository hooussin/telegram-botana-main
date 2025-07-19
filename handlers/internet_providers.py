# -*- coding: utf-8 -*-
# handlers/internet_providers.py  (Inline + موافقة أدمن قبل الخصم + رد أدمن للمستخدم)
#
# التعديلات حسب الطلب:
# - لا يُخصم من محفظة المستخدم قبل موافقة الأدمن.
# - عند ضغط المستخدم "تأكيد" يُنشأ طلب (PENDING) ويُرسل للأدمن بلوحة (قبول/رفض/رسالة للمستخدم).
# - عند رفض الأدمن: يُزال الطلب ويُرسل تنويه للمستخدم (يمكن إضافة سبب/صورة).
# - عند قبول الأدمن: يتم التحقق من الرصيد في لحظة القبول؛
#   * إن كان غير كافٍ -> لا خصم، يُخبر الأدمن والمستخدم بالمبلغ الناقص.
#   * إن كان كافياً -> يُخصم ثم يُؤكَّد التنفيذ.
# - تحديث نص طلب الرقم: "أرسل رقم الهاتف / الحساب المطلوب شحنه (مع رمز المحافظة، مثال: 011XXXXXXX)".
#
# ملاحظة: استُخدِم تخزين بسيط بالذاكرة (pending_orders) لإدارة الطلبات بانتظار موافقة الأدمن.
#         إن رغبت تخزينها بقاعدة بياناتك، عدِّل الدوال _create_pending_order / _get_pending / _del_pending.

from telebot import types
from database.models.product import Product
from services.wallet_service import add_purchase, has_sufficient_balance
from config import ADMIN_MAIN_ID
import logging

# ============================
#        الثوابت الأصلية
# ============================
INTERNET_PROVIDERS = [
    "تراسل", "أم تي أن", "سيرياتيل", "آية", "سوا", "رن نت", "سما نت", "أمنية",
    "ناس", "هايبر نت", "MTS", "يارا", "دنيا", "آينت"
]

INTERNET_SPEEDS = [
    {"label": "1 ميغا", "price": 19500},
    {"label": "2 ميغا", "price": 25000},
    {"label": "4 ميغا", "price": 39000},
    {"label": "8 ميغا", "price": 65000},
    {"label": "16 ميغا", "price": 84000},
]

COMMISSION_PER_5000 = 600
user_net_state = {}  # {user_id: {step, provider?, speed?, price?, phone?}}


# ============================
#   حساب العمولة المجمّعة
# ============================
def calculate_commission(amount: int) -> int:
    if amount <= 0:
        return 0
    blocks = (amount + 5000 - 1) // 5000  # تقريب للأعلى
    return blocks * COMMISSION_PER_5000


# ============================
#   مفاتيح callback
# ============================
CB_PROV_PREFIX = "iprov"       # اختيار مزوّد
CB_SPEED_PREFIX = "ispeed"     # اختيار سرعة (index)
CB_BACK_PROV = "iback_prov"    # رجوع لقائمة المزودين
CB_BACK_SPEED = "iback_speed"  # رجوع لقائمة السرعات
CB_CONFIRM = "iconfirm"        # تأكيد الطلب (يرسَل للأدمن ولا خصم)
CB_CANCEL = "icancel"          # إلغاء من جهة المستخدم

# أدمن
CB_ADM_APPROVE_PREFIX = "iadm_ok"   # iadm_ok:<oid>
CB_ADM_REJECT_PREFIX  = "iadm_no"   # iadm_no:<oid>
CB_ADM_MSG_PREFIX     = "iadm_msg"  # iadm_msg:<oid>  (إرسال رسالة/صورة للمستخدم)


# ============================
#   تخزين طلبات معلّقة بانتظار الأدمن
# ============================
# structure: {oid: {user_id, provider, speed, phone, price, comm, total, status}}
# status: PENDING | APPROVED | REJECTED
pending_orders = {}
_next_oid = 1

def _new_oid() -> int:
    global _next_oid
    oid = _next_oid
    _next_oid += 1
    return oid

def _create_pending_order(data: dict) -> int:
    oid = _new_oid()
    pending_orders[oid] = {**data, "status": "PENDING"}
    return oid

def _get_pending(oid: int):
    return pending_orders.get(oid)

def _del_pending(oid: int):
    pending_orders.pop(oid, None)


# ============================
#   توليد لوحات Inline
# ============================
def _provider_inline_kb() -> types.InlineKeyboardMarkup:
    """لوحة اختيار مزوّد (telebot: استخدم add(*btns))."""
    kb = types.InlineKeyboardMarkup(row_width=2)
    btns = [types.InlineKeyboardButton(f"🌐 {name}", callback_data=f"{CB_PROV_PREFIX}:{name}") for name in INTERNET_PROVIDERS]
    if btns:
        kb.add(*btns)
    kb.add(types.InlineKeyboardButton("❌ إلغاء", callback_data=CB_CANCEL))
    return kb

def _speeds_inline_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    btns = []
    for idx, speed in enumerate(INTERNET_SPEEDS):
        btns.append(
            types.InlineKeyboardButton(
                text=f"{speed['label']} - {speed['price']:,} ل.س",
                callback_data=f"{CB_SPEED_PREFIX}:{idx}"
            )
        )
    if btns:
        kb.add(*btns)
    kb.add(types.InlineKeyboardButton("⬅️ رجوع", callback_data=CB_BACK_PROV))
    return kb

def _confirm_inline_kb() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("✅ تأكيد", callback_data=CB_CONFIRM))
    kb.add(types.InlineKeyboardButton("⬅️ تعديل", callback_data=CB_BACK_SPEED))
    kb.add(types.InlineKeyboardButton("❌ إلغاء", callback_data=CB_CANCEL))
    return kb

def _admin_order_kb(oid: int) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ موافقة", callback_data=f"{CB_ADM_APPROVE_PREFIX}:{oid}"),
        types.InlineKeyboardButton("❌ رفض", callback_data=f"{CB_ADM_REJECT_PREFIX}:{oid}")
    )
    kb.add(types.InlineKeyboardButton("💬 رسالة للمستخدم", callback_data=f"{CB_ADM_MSG_PREFIX}:{oid}"))
    return kb


# ============================
#   بدء قائمة مزودي الإنترنت
# ============================
def start_internet_provider_menu(bot, message):
    bot.send_message(
        message.chat.id,
        "⚠️ اختر أحد مزودات الإنترنت:\n💸 العمولة لكل 5000 ل.س = 600 ل.س",
        reply_markup=_provider_inline_kb()
    )
    user_net_state[message.from_user.id] = {"step": "choose_provider"}


# ============================
#   أدوات داخلية مساعدة
# ============================
import re
_PHONE_RE = re.compile(r"[+\d]+")

def _normalize_phone(txt: str) -> str:
    if not txt:
        return ""
    clean = txt.replace(" ", "").replace("-", "").replace("_", "")
    m = _PHONE_RE.findall(clean)
    return ''.join(m)


# ============================
#   التسجيل في البوت
# ============================
def register(bot):
    """تسجيل معالجات مزودي الإنترنت."""

    # --- فتح القائمة من زر رئيسي (للتوافق) ---
    @bot.message_handler(func=lambda msg: msg.text == "🌐 دفع مزودات الإنترنت ADSL")
    def open_net_menu(msg):
        start_internet_provider_menu(bot, msg)


    # =========================
    #      CALLBACK HANDLERS
    # =========================

    # اختيار مزوّد
    @bot.callback_query_handler(func=lambda c: c.data.startswith(f"{CB_PROV_PREFIX}:"))
    def cb_choose_provider(call):
        user_id = call.from_user.id
        provider = call.data.split(":", 1)[1]
        if provider not in INTERNET_PROVIDERS:
            bot.answer_callback_query(call.id, "خيار غير صالح.")
            return
        user_net_state[user_id] = {"step": "choose_speed", "provider": provider}
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="⚡ اختر السرعة المطلوبة:\n💸 العمولة لكل 5000 ل.س = 600 ل.س",
            reply_markup=_speeds_inline_kb()
        )


    # رجوع من السرعات إلى قائمة المزودين
    @bot.callback_query_handler(func=lambda c: c.data == CB_BACK_PROV)
    def cb_back_to_prov(call):
        user_id = call.from_user.id
        user_net_state[user_id] = {"step": "choose_provider"}
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="⚠️ اختر أحد مزودات الإنترنت:\n💸 العمولة لكل 5000 ل.س = 600 ل.س",
            reply_markup=_provider_inline_kb()
        )


    # اختيار سرعة
    @bot.callback_query_handler(func=lambda c: c.data.startswith(f"{CB_SPEED_PREFIX}:"))
    def cb_choose_speed(call):
        user_id = call.from_user.id
        try:
            idx = int(call.data.split(":", 1)[1])
            speed = INTERNET_SPEEDS[idx]
        except (ValueError, IndexError):
            bot.answer_callback_query(call.id, "خيار غير صالح.")
            return

        st = user_net_state.setdefault(user_id, {})
        st.update({"step": "enter_phone", "speed": speed["label"], "price": speed["price"]})

        bot.answer_callback_query(call.id)
        bot.send_message(
            call.message.chat.id,
            "📱 أرسل رقم الهاتف / الحساب المطلوب شحنه (مع رمز المحافظة، مثال: 011XXXXXXX).\nأرسل /cancel للإلغاء."
        )


    # رجوع من شاشة التأكيد إلى السرعات
    @bot.callback_query_handler(func=lambda c: c.data == CB_BACK_SPEED)
    def cb_back_to_speed(call):
        user_id = call.from_user.id
        st = user_net_state.get(user_id, {})
        if "provider" not in st:  # احتياط
            return cb_back_to_prov(call)
        st["step"] = "choose_speed"
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="⚡ اختر السرعة المطلوبة:\n💸 العمولة لكل 5000 ل.س = 600 ل.س",
            reply_markup=_speeds_inline_kb()
        )


    # إلغاء كامل (مستخدم)
    @bot.callback_query_handler(func=lambda c: c.data == CB_CANCEL)
    def cb_cancel(call):
        user_net_state.pop(call.from_user.id, None)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="تم الإلغاء. أرسل /start للعودة إلى القائمة الرئيسية."
        )


    # =========================
    #   مرحلة إدخال الهاتف
    # =========================
    @bot.message_handler(func=lambda m: user_net_state.get(m.from_user.id, {}).get("step") == "enter_phone")
    def handle_phone_entry(msg):
        user_id = msg.from_user.id
        phone = _normalize_phone(msg.text)
        if not phone or len(phone) < 5:
            return bot.reply_to(msg, "⚠️ رقم غير صالح، أعد الإرسال.")

        st = user_net_state[user_id]
        st["phone"] = phone
        st["step"] = "confirm"

        price = st["price"]
        comm = calculate_commission(price)
        total = price + comm

        summary = (
            "📦 *تفاصيل الطلب*\n"
            f"مزود: {st['provider']}\n"
            f"سرعة: {st['speed']}\n"
            f"السعر: {price:,} ل.س\n"
            f"العمولة: {comm:,} ل.س\n"
            f"الإجمالي: {total:,} ل.س\n\n"
            f"رقم: `{phone}`\n\n"
            "اضغط لإرسال الطلب إلى الأدمن (لن يتم خصم أي مبلغ الآن)."
        )

        bot.send_message(
            msg.chat.id,
            summary,
            parse_mode="Markdown",
            reply_markup=_confirm_inline_kb()
        )


    # =========================
    #   إرسال الطلب للأدمن (لا خصم)
    # =========================
    @bot.callback_query_handler(func=lambda c: c.data == CB_CONFIRM)
    def cb_confirm(call):
        user_id = call.from_user.id
        st = user_net_state.get(user_id)
        if not st or st.get("step") != "confirm":
            bot.answer_callback_query(call.id, "انتهت صلاحية هذا الطلب.", show_alert=True)
            return

        price = st["price"]
        comm = calculate_commission(price)
        total = price + comm

        order_data = {
            "user_id": user_id,
            "provider": st['provider'],
            "speed": st['speed'],
            "phone": st['phone'],
            "price": price,
            "comm": comm,
            "total": total,
        }
        oid = _create_pending_order(order_data)

        # إنشاء سجل المنتج بوضع PENDING (اختياري حسب نموذج DB)
        try:
            Product.create(
                user_id=user_id,
                provider=st['provider'],
                speed=st['speed'],
                phone=st['phone'],
                amount=price,
                commission=comm,
                total=total,
                status="PENDING",
                ext_id=oid,  # إن كان لديك حقل خارجي
            )
        except Exception as e:  # pylint: disable=broad-except
            bot.send_message(ADMIN_MAIN_ID, f"[internet_providers] خطأ حفظ المنتج (PENDING): {e}")

        bot.answer_callback_query(call.id, "تم إرسال الطلب للأدمن.", show_alert=False)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="📨 تم إرسال طلبك لمسؤول البوت. سيتم إشعارك بعد المراجعة.",
        )

        # رسالة للأدمن مع لوحة الموافقة
        adm_txt = (
            "📥 *طلب جديد (إنترنت)*\n"
            f"OID: {oid}\n"
            f"المستخدم: {user_id}\n"
            f"مزود: {st['provider']}\n"
            f"سرعة: {st['speed']}\n"
            f"رقم: {st['phone']}\n"
            f"المبلغ: {price:,} + عمولة {comm:,} = {total:,} ل.س"
        )
        bot.send_message(
            ADMIN_MAIN_ID,
            adm_txt,
            parse_mode="Markdown",
            reply_markup=_admin_order_kb(oid)
        )

        # لا نحذف الحالة كي لا يفقد المستخدم المعلومات؛ لكن نضع step=wait_admin
        st["step"] = "wait_admin"


    # =========================
    #   أدمن: موافقة
    # =========================
    @bot.callback_query_handler(func=lambda c: c.data.startswith(f"{CB_ADM_APPROVE_PREFIX}:"))
    def cb_adm_approve(call):
        if call.from_user.id != ADMIN_MAIN_ID:
            bot.answer_callback_query(call.id, "غير مخوَّل.", show_alert=True)
            return

        oid = int(call.data.split(":", 1)[1])
        order = _get_pending(oid)
        if not order or order.get("status") != "PENDING":
            bot.answer_callback_query(call.id, "الطلب غير متاح.", show_alert=True)
            return

        user_id = order["user_id"]
        total = order["total"]

        # تحقق من الرصيد الآن
        enough = has_sufficient_balance(user_id, total)
        if not enough:
            # احسب المبلغ الناقص إن أمكن
            shortage = None
            if get_balance:
                try:
                    bal = get_balance(user_id)
                    shortage = total - bal
                except Exception:
                    shortage = None
            bot.answer_callback_query(call.id, "رصيد المستخدم غير كافٍ.", show_alert=True)

            # رسالة للأدمن
            txt_adm = f"⚠️ لا يوجد رصيد كافٍ لدى المستخدم {user_id}. المطلوب: {total:,} ل.س."
            if shortage and shortage > 0:
                txt_adm += f" (الناقص: {shortage:,} ل.س)"
            bot.send_message(call.message.chat.id, txt_adm)

            # تنويه للمستخدم
            txt_usr = f"⚠️ لا يكفي رصيدك لإتمام الطلب OID {oid}. المبلغ المطلوب: {total:,} ل.س."
            if shortage and shortage > 0:
                txt_usr += f" المبلغ الناقص: {shortage:,} ل.س."
            bot.send_message(user_id, txt_usr)
            return

        # خصم الرصيد
        deduct_balance(user_id, total)

        # تحديث DB (إن أمكن)
        try:
            Product.update(status="APPROVED").where(Product.ext_id == oid).execute()
        except Exception:
            pass

        # إشعار المستخدم
        bot.send_message(user_id, f"✅ تم قبول طلبك (OID {oid}). سيتم التنفيذ قريبًا.")

        # تحديث رسالة الأدمن
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"تمت الموافقة على الطلب OID {oid} وتم الخصم من رصيد المستخدم.",
        )

        order["status"] = "APPROVED"
        _del_pending(oid)


    # =========================
    #   أدمن: رفض
    # =========================
    @bot.callback_query_handler(func=lambda c: c.data.startswith(f"{CB_ADM_REJECT_PREFIX}:"))
    def cb_adm_reject(call):
        if call.from_user.id != ADMIN_MAIN_ID:
            bot.answer_callback_query(call.id, "غير مخوَّل.", show_alert=True)
            return

        oid = int(call.data.split(":", 1)[1])
        order = _get_pending(oid)
        if not order or order.get("status") != "PENDING":
            bot.answer_callback_query(call.id, "الطلب غير متاح.", show_alert=True)
            return

        order["status"] = "REJECTED"
        bot.answer_callback_query(call.id)

        # نطلب من الأدمن إرسال سبب أو صورة (اختياري)
        bot.send_message(call.message.chat.id, f"أرسل سبب/رسالة (أو صورة) لرفض الطلب OID {oid}.")
        admin_reply_state['awaiting'][call.from_user.id] = ('reject', oid)


    # =========================
    #   أدمن: إرسال رسالة للمستخدم (بدون قبول/رفض)
    # =========================
    @bot.callback_query_handler(func=lambda c: c.data.startswith(f"{CB_ADM_MSG_PREFIX}:"))
    def cb_adm_msg(call):
        if call.from_user.id != ADMIN_MAIN_ID:
            bot.answer_callback_query(call.id, "غير مخوَّل.", show_alert=True)
            return

        oid = int(call.data.split(":", 1)[1])
        order = _get_pending(oid)
        if not order:
            bot.answer_callback_query(call.id, "الطلب غير متاح.", show_alert=True)
            return

        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, f"أرسل رسالة (أو صورة) للمستخدم بخصوص الطلب OID {oid}.")
        admin_reply_state['awaiting'][call.from_user.id] = ('msg', oid)


    # =========================
    #   حالات انتظار رد أدمن (رسالة أو صورة)
    # =========================
    admin_reply_state = {'awaiting': {}}  # {admin_id: (mode, oid)}

    @bot.message_handler(content_types=['text', 'photo'], func=lambda m: m.from_user.id == ADMIN_MAIN_ID and m.from_user.id in admin_reply_state['awaiting'])
    def admin_reply_handler(msg):
        mode, oid = admin_reply_state['awaiting'].pop(msg.from_user.id)
        order = _get_pending(oid)
        user_id = order["user_id"] if order else None

        if not user_id:
            bot.reply_to(msg, "لم يتم العثور على المستخدم.")
            return

        # إعادة توجيه / إرسال
        if msg.content_type == 'photo':
            # أكبر دقة هي آخر عنصر
            file_id = msg.photo[-1].file_id
            caption = msg.caption or ""
            bot.send_photo(user_id, file_id, caption=caption)
        else:
            bot.send_message(user_id, msg.text)

        if mode == 'reject':
            # إعلام المستخدم بالرفض (إن لم يُذكر في الرسالة)
            bot.send_message(user_id, f"❌ تم رفض طلبك OID {oid}.")
            # تحديث DB
            try:
                Product.update(status="REJECTED").where(Product.ext_id == oid).execute()
            except Exception:
                pass
            _del_pending(oid)
            bot.reply_to(msg, f"تم رفض الطلب OID {oid} وإبلاغ المستخدم.")
        else:
            bot.reply_to(msg, f"تم إرسال رسالتك للمستخدم (OID {oid}).")


    # =========================
    #   /cancel أثناء إدخال الرقم
    # =========================
    @bot.message_handler(commands=['cancel'])
    def cancel_cmd(msg):
        user_net_state.pop(msg.from_user.id, None)
        bot.send_message(msg.chat.id, "تم الإلغاء. أرسل /start للعودة للقائمة.")


    # =========================
    #   احتياط: رجوع يدوي بالنص
    # =========================
    @bot.message_handler(func=lambda m: m.text == "⬅️ رجوع")
    def txt_back(msg):
        start_internet_provider_menu(bot, msg)
