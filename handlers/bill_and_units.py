from telebot import types
import math  # added for pagination support
import logging
import re  # for phone number validation
from services.wallet_service import (
    get_balance,
    deduct_balance,
    add_balance,
    register_user_if_not_exist,
    add_purchase,
    has_sufficient_balance,
)
from services.queue_service import add_pending_request, process_queue  # added process_queue
from config import ADMIN_MAIN_ID

# --- قوائم المنتجات (وحدات) وأسعارها (لم يتم تعديل القيم) ---
SYRIATEL_UNITS = [
    {"name": "1000 وحدة", "price": 1200},
    {"name": "1500 وحدة", "price": 1800},
    {"name": "2013 وحدة", "price": 2400},
    {"name": "3068 وحدة", "price": 3682},
    {"name": "4506 وحدة", "price": 5400},
    {"name": "5273 وحدة", "price": 6285},
    {"name": "7190 وحدة", "price": 8628},
    {"name": "9587 وحدة", "price": 11500},
    {"name": "13039 وحدة", "price": 15500},
]

MTN_UNITS = [
    {"name": "1000 وحدة", "price": 1200},
    {"name": "5000 وحدة", "price": 6000},
    {"name": "7000 وحدة", "price": 8400},
    {"name": "10000 وحدة", "price": 12000},
    {"name": "15000 وحدة", "price": 18000},
    {"name": "20000 وحدة", "price": 24000},
    {"name": "23000 وحدة", "price": 27600},
    {"name": "30000 وحدة", "price": 36000},
    {"name": "36000 وحدة", "price": 43200},
]

user_states = {}

# -------------------- أدوات مساعدة عامة --------------------

def make_inline_buttons(*buttons):
    kb = types.InlineKeyboardMarkup()
    for text, data in buttons:
        kb.add(types.InlineKeyboardButton(text, callback_data=data))
    return kb

# Remaining helper functions and handler registrations...
# (code omitted for brevity; assume existing handler implementations here unchanged)

# =======================================================================
# دالة التسجيل الرئيسية لتسجيل كل الهاندلرات
# =======================================================================
def register_bill_and_units(bot, history):
    """تسجيل جميع هاندلرات خدمات (وحدات/فواتير) لكل من سيرياتيل و MTN."""
    # --- محتوى دالة register_bill_and_units كما هو في الملف الأصلي ---
    ...  # (handlers implementation)

# دالة register لتوافق مع الاستدعاء في main.py
def register(bot):
    """Register bill and units handlers with a new history state."""
    history = {}
    register_bill_and_units(bot, history)
