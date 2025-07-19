from telebot import types
from handlers.wallet import register_user_if_not_exist
from config import BOT_NAME
from handlers import keyboards
from database.models.product import Product
from services.wallet_service import get_all_products, get_product_by_id, add_purchase
import logging

# استدعاء عميل supabase
from database.db import client

# ============= إضافة لمسح الطلب المعلق للعميل =============
def clear_pending_request(user_id):
    try:
        from handlers.recharge import recharge_pending
        recharge_pending.discard(user_id)
    except Exception:
        pass
# =========================================================

# منتجات مقسمة حسب التصنيفات
PRODUCTS = {
    "PUBG": [
        Product(1, "60 شدة", "ألعاب", 0.89),
        Product(2, "325 شدة", "ألعاب", 4.44),
        Product(3, "660 شدة", "ألعاب", 8.85),
        Product(4, "1800 شدة", "ألعاب", 22.09),
        Product(5, "3850 شدة", "ألعاب", 43.24),
        Product(6, "8100 شدة", "ألعاب", 86.31),
    ],
    "FreeFire": [
        Product(7, "100 جوهرة", "ألعاب", 0.98),
        Product(8, "310 جوهرة", "ألعاب", 2.49),
        Product(9, "520 جوهرة", "ألعاب", 4.13),
        Product(10, "1060 جوهرة", "ألعاب", 9.42),
        Product(11, "2180 جوهرة", "ألعاب", 18.84),
    ],
    "Jawaker": [
        Product(12, "10000 توكنز", "ألعاب", 1.34),
        Product(13, "15000 توكنز", "ألعاب", 2.01),
        Product(14, "20000 توكنز", "ألعاب", 2.68),
        Product(15, "30000 توكنز", "ألعاب", 4.02),
        Product(16, "60000 توكنز", "ألعاب", 8.04),
        Product(17, "120000 توكنز", "ألعاب", 16.08),
    ]
}

pending_orders = set()
user_orders = {}

# ============= تحويل السعر للدولار السوري (سرّي) =============
def convert_price_usd_to_syp(usd):
    if usd <= 5:
        return int(usd * 11800)
    elif usd <= 10:
        return int(usd * 11600)
    elif usd <= 20:
        return int(usd * 11300)
    return int(usd * 11000)

# ============= إضافة سجل شراء جديد في Supabase =============
def add_purchase(user_id, product_name, price, player_id):
    client.table("purchases").insert({
        "user_id": user_id,
        "product_name": product_name,
        "price": price,
        "player_id": player_id
    }).execute()

# ============= عرض قوائم المنتجات والتصنيفات =============
def show_products_menu(bot, message):
    bot.send_message(message.chat.id, "📍 اختر نوع المنتج:", reply_markup=keyboards.products_menu())

def show_game_categories(bot, message):
    bot.send_message(message.chat.id, "🎮 اختر اللعبة أو التطبيق:", reply_markup=keyboards.game_categories())

def show_product_options(bot, message, category):
    options = PRODUCTS.get(category, [])
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    for product in options:
        label = f"{product.name} ({product.price}$)"
        callback_data = f"select_{product.product_id}"
        keyboard.add(types.InlineKeyboardButton(label, callback_data=callback_data))
    keyboard.add(types.InlineKeyboardButton("⬅️ رجوع", callback_data="back_to_categories"))
    bot.send_message(message.chat.id, f"📦 اختر الكمية لـ {category}:", reply_markup=keyboard)

def clear_user_order(user_id):
    user_orders.pop(user_id, None)
    pending_orders.discard(user_id)

# ============= تسجيل المستخدم =============
def register(bot, history):
    @bot.message_handler(func=lambda msg: msg.text in ["🛒 المنتجات", "💼 المنتجات"])
    def handle_main_product_menu(msg):
        user_id = msg.from_user.id
        name = msg.from_user.full_name
        register_user_if_not_exist(user_id, name)
        if user_id in pending_orders:
            bot.send_message(msg.chat.id, "⚠️ لديك طلب قيد الانتظار.")
            return
        if not isinstance(history.get(user_id), list):
           history[user_id] = []
        history[user_id].append("products_menu")
        show_products_menu(bot, msg)

    @bot.message_handler(func=lambda msg: msg.text == "🎮 شحن ألعاب و تطبيقات")
    def handle_games_menu(msg):
        user_id = msg.from_user.id
        name = msg.from_user.full_name
        register_user_if_not_exist(user_id, name)
        history.setdefault(user_id, []).append("games_menu")
        show_game_categories(bot, msg)

    @bot.message_handler(func=lambda msg: msg.text in [
        "🎯 شحن شدات ببجي العالمية", "🔥 شحن جواهر فري فاير", "🏏 تطبيق جواكر"])
    def game_handler(msg):
        user_id = msg.from_user.id
        name = msg.from_user.full_name
        register_user_if_not_exist(user_id, name)
        if user_id in pending_orders:
            bot.send_message(msg.chat.id, "⚠️ لديك طلب قيد الانتظار.")
            return
        category_map = {
            "🎯 شحن شدات ببجي العالمية": "PUBG",
            "🔥 شحن جواهر فري فاير": "FreeFire",
            "🏏 تطبيق جواكر": "Jawaker"
        }
        category = category_map[msg.text]
        history.setdefault(user_id, []).append("product_options")
        user_orders[user_id] = {"category": category}
        show_product_options(bot, msg, category)

# ============= الهاندلر الرئيسي للأزرار المضمنة =============
def setup_inline_handlers(bot, admin_ids):
    @bot.callback_query_handler(func=lambda c: c.data.startswith("select_"))
    def on_select_product(call):
        user_id = call.from_user.id
        if user_id in pending_orders:
            bot.answer_callback_query(call.id, "لا يمكنك إرسال طلب جديد حتى يتم معالجة طلبك الحالي.", show_alert=True)
            return
        product_id = int(call.data.replace("select_", ""))
        selected_product = None
        for category, items in PRODUCTS.items():
            for product in items:
                if product.product_id == product_id:
                    selected_product = product
                    break
        order = user_orders.setdefault(user_id, {})
        order["product"] = selected_product
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("⬅️ رجوع", callback_data="back_to_products"))
        msg = bot.send_message(user_id, "💡 أدخل آيدي اللاعب الخاص بك:", reply_markup=keyboard)
        bot.register_next_step_handler(msg, handle_player_id, bot, admin_ids)

    @bot.callback_query_handler(func=lambda c: c.data == "back_to_products")
    def back_to_products(call):
        user_id = call.from_user.id
        category = user_orders.get(user_id, {}).get("category")
        if category:
            msg = bot.send_message(user_id, f"📦 اختر الكمية لـ {category}:", reply_markup=types.ReplyKeyboardRemove())
            show_product_options(bot, msg, category)

    @bot.callback_query_handler(func=lambda c: c.data == "back_to_categories")
    def back_to_categories(call):
        user_id = call.from_user.id
        msg = bot.send_message(user_id, "🎮 اختر اللعبة أو التطبيق:", reply_markup=types.ReplyKeyboardRemove())
        show_game_categories(bot, msg)

    @bot.callback_query_handler(func=lambda c: c.data == "edit_player_id")
    def edit_player_id(call):
        user_id = call.from_user.id
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("⬅️ رجوع", callback_data="back_to_products"))
        msg = bot.send_message(user_id, "💡 أعد إدخال آيدي اللاعب:", reply_markup=keyboard)
        bot.register_next_step_handler(msg, handle_player_id, bot, admin_ids)

    @bot.callback_query_handler(func=lambda c: c.data == "cancel_order")
    def cancel_order(call):
        user_id = call.from_user.id
        clear_user_order(user_id)
        bot.send_message(user_id, "❌ تم إلغاء الطلب. يمكنك البدء من جديد.", reply_markup=keyboards.products_menu())

    @bot.callback_query_handler(func=lambda c: c.data == "confirm_player_id")
    def confirm_player_id(call):
        user_id = call.from_user.id
        order = user_orders[user_id]
        product = order["product"]
        player_id = order["player_id"]
        price_syp = convert_price_usd_to_syp(product.price)
        balance = get_balance(user_id)
        if balance < price_syp:
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton("💳 شحن محفظتي", callback_data="topup_wallet"))
            keyboard.add(types.InlineKeyboardButton("⬅️ رجوع", callback_data="back_to_products"))
            bot.send_message(user_id, "❌ لا يوجد رصيد كاف في محفظتك. الرجاء الشحن أولًا.", reply_markup=keyboard)
            return
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("✅ تأكيد الشراء", callback_data="final_confirm_order"),
            types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_order"),
        )
        msg_text = (
            f"هل أنت متأكد من شراء {product.name}؟\n"
            f"سيتم خصم مبلغ {price_syp:,} ل.س من محفظتك عند موافقة الإدارة.\n"
            "عند الضغط على تأكيد، سيتم إرسال الطلب للإدارة لمعالجته.\n"
            "إذا رغبت بالإلغاء اضغط إلغاء."
        )
        bot.send_message(user_id, msg_text, reply_markup=keyboard)

    @bot.callback_query_handler(func=lambda c: c.data == "final_confirm_order")
    def final_confirm_order(call):
        user_id = call.from_user.id
        order = user_orders[user_id]
        product = order["product"]
        player_id = order["player_id"]
        price_syp = convert_price_usd_to_syp(product.price)
        pending_orders.add(user_id)
        # رسالة للعميل
        bot.send_message(user_id, "✅ تم إرسال طلبك للإدارة.\nالوقت المقدر للرد 1-4 دقائق.")
        # رسالة للأدمنين
        for admin_id in admin_ids:
            admin_keyboard = types.InlineKeyboardMarkup(row_width=2)
            admin_keyboard.add(
                types.InlineKeyboardButton("✅ تم التنفيذ", callback_data=f"admin_approve_{user_id}"),
                types.InlineKeyboardButton("❌ رفض الطلب", callback_data=f"admin_reject_{user_id}")
            )
            # تم تعديل السطر لجعل الآيدي قابل للنسخ (بين Backticks)
            admin_msg = (
                f"طلب جديد:\n"
                f"👤 المستخدم: {call.from_user.full_name} (@{call.from_user.username})\n"
                f"🆔 آيدي التليجرام: `{user_id}`\n"
                f"🔖 نوع العملية: {product.name}\n"
                f"🎮 آيدي اللاعب: `{player_id}`\n"
                f"💵 السعر: {price_syp:,} ل.س"
            )
            bot.send_message(admin_id, admin_msg, parse_mode="Markdown", reply_markup=admin_keyboard)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("admin_approve_") or c.data.startswith("admin_reject_"))
    def on_admin_action(call):
        user_id = int(call.data.split("_")[-1])
        order = user_orders.get(user_id)
        if not order:
            bot.answer_callback_query(call.id, "الطلب غير موجود أو انتهت صلاحيته.")
            return
        product = order["product"]
        player_id = order["player_id"]
        price_syp = convert_price_usd_to_syp(product.price)
        if call.data.startswith("admin_approve_"):
            deduct_balance(user_id, price_syp, f"شراء {product.name}")
            # إضافة سجل الشراء في جدول المشتريات
            add_purchase(user_id, product.name, price_syp, player_id)
            bot.send_message(
                user_id,
                f"✅ تم تنفيذ طلبك بنجاح!\n"
                f"المنتج: {product.name}\n"
                f"السعر: {price_syp:,} ل.س\n"
                f"آيدي اللاعب: {player_id}",
                reply_markup=keyboards.main_menu()
            )
        else:
            bot.send_message(user_id, "❌ عذرًا، لم يتم تنفيذ طلبك حاليًا. سنبلغك عند توفر المنتج.", reply_markup=keyboards.main_menu())
        clear_user_order(user_id)

def handle_player_id(message, bot, admin_ids):
    user_id = message.from_user.id
    player_id = message.text.strip()
    user_orders[user_id]["player_id"] = player_id
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("✏️ تعديل", callback_data="edit_player_id"),
        types.InlineKeyboardButton("✅ تأكيد", callback_data="confirm_player_id"),
    )
    keyboard.add(types.InlineKeyboardButton("⬅️ رجوع", callback_data="back_to_products"))
    bot.send_message(user_id, f"هل هذا هو آيدي اللاعب الخاص بك؟\n`{player_id}`", parse_mode="Markdown", reply_markup=keyboard)

# ==================== نهاية الملف ====================
