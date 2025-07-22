# handlers/products.py

import logging
from telebot import types
from services.wallet_service import register_user_if_not_exist, get_balance
from config import BOT_NAME
from handlers import keyboards
from database.models.product import Product
from services.queue_service import add_pending_request, process_queue

# استدعاء عميل supabase
from database.db import client

# حفظ الطلبات المعلقة
pending_orders = set()
user_orders = {}

# ============= تعريف المنتجات =============
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
    ],
}

# ============= تحويل السعر من USD إلى SYP =============
def convert_price_usd_to_syp(usd):
    if usd <= 5:
        return int(usd * 11800)
    elif usd <= 10:
        return int(usd * 11600)
    elif usd <= 20:
        return int(usd * 11300)
    return int(usd * 11000)

# ============= قوائم الواجهات =============
def show_products_menu(bot, message):
    bot.send_message(message.chat.id, "📍 اختر نوع المنتج:", reply_markup=keyboards.products_menu())

def show_game_categories(bot, message):
    bot.send_message(message.chat.id, "🎮 اختر اللعبة أو التطبيق:", reply_markup=keyboards.game_categories())

def show_product_options(bot, message, category):
    options = PRODUCTS.get(category, [])
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    for p in options:
        keyboard.add(types.InlineKeyboardButton(f"{p.name} ({p.price}$)", callback_data=f"select_{p.product_id}"))
    keyboard.add(types.InlineKeyboardButton("⬅️ رجوع", callback_data="back_to_categories"))
    bot.send_message(message.chat.id, f"📦 اختر الكمية لـ {category}:", reply_markup=keyboard)

def clear_user_order(user_id):
    user_orders.pop(user_id, None)
    pending_orders.discard(user_id)

# ============= بعد إدخال آيدي اللاعب =============
def handle_player_id(message):
    bot = message.bot
    user_id = message.from_user.id
    player_id = message.text.strip()

    order = user_orders.get(user_id)
    if not order or "product" not in order:
        bot.send_message(user_id, "❌ لم يتم تحديد طلب صالح.")
        return

    order["player_id"] = player_id
    product = order["product"]
    price_syp = convert_price_usd_to_syp(product.price)

    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("✅ تأكيد الطلب", callback_data="final_confirm_order"),
        types.InlineKeyboardButton("❌ إلغاء",         callback_data="cancel_order")
    )

    bot.send_message(
        user_id,
        (
            f"هل أنت متأكد من شراء {product.name}؟\n"
            f"سيتم خصم {price_syp:,} ل.س من محفظتك عند موافقة الإدارة."
        ),
        reply_markup=keyboard
    )

# ============= تسجيل الواجهات =============
def register(bot, history):
    @bot.message_handler(func=lambda msg: msg.text in ["🛒 المنتجات", "💼 المنتجات"])
    def handle_main_product_menu(msg):
        user_id = msg.from_user.id
        register_user_if_not_exist(user_id, msg.from_user.full_name)
        if user_id in pending_orders:
            bot.send_message(msg.chat.id, "⚠️ لديك طلب قيد الانتظار.")
            return
        history.setdefault(user_id, []).append("products_menu")
        show_products_menu(bot, msg)

    @bot.message_handler(func=lambda msg: msg.text == "🎮 شحن ألعاب و تطبيقات")
    def handle_games_menu(msg):
        user_id = msg.from_user.id
        register_user_if_not_exist(user_id, msg.from_user.full_name)
        history.setdefault(user_id, []).append("games_menu")
        show_game_categories(bot, msg)

    @bot.message_handler(func=lambda msg: msg.text in [
        "🎯 شحن شدات ببجي العالمية",
        "🔥 شحن جواهر فري فاير",
        "🏏 تطبيق جواكر"
    ])
    def game_handler(msg):
        user_id = msg.from_user.id
        register_user_if_not_exist(user_id, msg.from_user.full_name)
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

    @bot.callback_query_handler(func=lambda c: c.data.startswith("select_"))
    def on_select_product(call):
        user_id = call.from_user.id
        if user_id in pending_orders:
            bot.answer_callback_query(call.id, "⚠️ لا يمكنك إرسال طلب جديد الآن.", show_alert=True)
            return
        product_id = int(call.data.split("_", 1)[1])
        # البحث في القاموس
        selected = None
        for items in PRODUCTS.values():
            for p in items:
                if p.product_id == product_id:
                    selected = p
                    break
            if selected:
                break
        if not selected:
            bot.answer_callback_query(call.id, "❌ المنتج غير موجود.")
            return
        user_orders[user_id] = {"category": selected.category, "product": selected}
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("⬅️ رجوع", callback_data="back_to_products"))
        msg = bot.send_message(user_id, "💡 أدخل آيدي اللاعب الخاص بك:", reply_markup=kb)
        bot.register_next_step_handler(msg, handle_player_id)

    @bot.callback_query_handler(func=lambda c: c.data == "back_to_products")
    def back_to_products(call):
        user_id = call.from_user.id
        category = user_orders.get(user_id, {}).get("category")
        if category:
            show_product_options(bot, call.message, category)

    @bot.callback_query_handler(func=lambda c: c.data == "back_to_categories")
    def back_to_categories(call):
        show_game_categories(bot, call.message)

    @bot.callback_query_handler(func=lambda c: c.data == "cancel_order")
    def cancel_order(call):
        user_id = call.from_user.id
        clear_user_order(user_id)
        bot.send_message(user_id, "❌ تم إلغاء الطلب.", reply_markup=keyboards.products_menu())

    @bot.callback_query_handler(func=lambda c: c.data == "final_confirm_order")
    def final_confirm_order(call):
        user_id = call.from_user.id
        order = user_orders.get(user_id)
        if not order or "product" not in order or "player_id" not in order:
            bot.answer_callback_query(call.id, "❌ لم يتم تجهيز الطلب بالكامل.")
            return
        product = order["product"]
        player_id = order["player_id"]
        price_syp = convert_price_usd_to_syp(product.price)

        pending_orders.add(user_id)
        bot.send_message(user_id, "✅ تم إرسال طلبك للإدارة. يرجى الانتظار 1–4 دقائق.")

        admin_msg = (
            f"🆕 طلب جديد من @{call.from_user.username or ''} (ID: {user_id}):\n"
            f"🔖 منتج: {product.name}\n"
            f"🎮 آيدي اللاعب: {player_id}\n"
            f"💵 السعر: {price_syp:,} ل.س"
        )
        add_pending_request(
            user_id=user_id,
            username=call.from_user.username,
            request_text=admin_msg
        )
        process_queue(bot)
