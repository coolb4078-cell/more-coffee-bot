import asyncio
import logging
import sqlite3
import sys
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiohttp import web

from config import ADMIN_IDS, BOT_TOKEN, DB_PATH

logging.basicConfig(level=logging.INFO)

# دیتابیس
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS inventory (
            name TEXT PRIMARY KEY,
            qty REAL,
            unit TEXT,
            min_qty REAL
        )"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS recipes (
            item_name TEXT,
            ingredient TEXT,
            amount REAL
        )"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT,
            qty REAL,
            total_price REAL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            amount REAL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    conn.commit()
    conn.close()


init_db()

# وضعیت‌های ربات
class Form(StatesGroup):
    waiting_for_input = State()


router = Router()


def is_admin(user_id: int) -> bool:
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS


def main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📦 موجودی انبار", callback_data="inv"),
                InlineKeyboardButton(text="⚠️ هشدارهای شارژ", callback_data="alerts"),
            ],
            [
                InlineKeyboardButton(text="☕ ثبت فروش", callback_data="add_sale"),
                InlineKeyboardButton(text="💸 ثبت هزینه", callback_data="add_expense"),
            ],
            [InlineKeyboardButton(text="📊 گزارش مالی", callback_data="report")],
        ]
    )


@router.message(Command("start"))
async def cmd_start(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ شما دسترسی به این ربات ندارید.")
        return
    await message.answer(
        "☕ به ربات مدیریت کافه **قهوه مور (MoRe Coffee)** خوش آمدید!\n\nلطفاً از منوی زیر یکی را انتخاب کنید:",
        reply_markup=main_menu(),
        parse_mode="Markdown",
    )


@router.callback_query(F.data == "inv")
async def show_inventory(callback: Message):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name, qty, unit, min_qty FROM inventory")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        text = (
            "📦 انبار خالی است.\nبرای اضافه کردن مواد اولیه از دکمه‌ها استفاده"
            " کنید."
        )
    else:
        text = "📦 **موجودی مواد اولیه انبار:**\n\n"
        for r in rows:
            text += f"• **{r[0]}**: {r[1]} {r[2]} (حداقل: {r[3]})\n"

    await callback.message.edit_text(
        text, reply_markup=main_menu(), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "alerts")
async def show_alerts(callback: Message):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name, qty, unit, min_qty FROM inventory WHERE qty <= min_qty"
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        text = "✅ همه چیز مرتب است! هیچ موردی نیاز به شارژ فوری ندارد."
    else:
        text = "⚠️ **هشدار شارژ سریع مواد اولیه:**\n\n"
        for r in rows:
            text += f"• **{r[0]}**: موجودی فعلی {r[1]} {r[2]} (کمتر از حد مجاز!)\n"

    await callback.message.edit_text(
        text, reply_markup=main_menu(), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "report")
async def show_report(callback: Message):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(total_price) FROM sales")
    total_sales = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(amount) FROM expenses")
    total_expenses = cursor.fetchone()[0] or 0
    conn.close()

    profit = total_sales - total_expenses
    text = (
        f"📊 **گزارش مالی کافه مور:**\n\n💰 کل فروش: `{total_sales:,.0f}` تومان\n💸"
        f" کل هزینه‌ها: `{total_expenses:,.0f}` تومان\n────────────────\n🏷️"
        f" سود خالص: `{profit:,.0f}` تومان"
    )

    await callback.message.edit_text(
        text, reply_markup=main_menu(), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "add_sale")
async def ask_sale(callback: Message, state: FSMContext):
    await callback.message.answer(
        "📝 لطفا فروش را به این صورت بفرستید:\n`نام آیتم, تعداد`\nمثال:\n`لاته,"
        " 2`",
        parse_mode="Markdown",
    )
    await state.set_state(Form.waiting_for_input)
    await state.update_data(action="sale")
    await callback.answer()


@router.callback_query(F.data == "add_expense")
async def ask_expense(callback: Message, state: FSMContext):
    await callback.message.answer(
        "💸 لطفا هزینه را به این صورت بفرستید:\n`عنوان هزینه, مبلغ (تومان)`\nمثال:\n`خرید"
        " شیر, 250000`",
        parse_mode="Markdown",
    )
    await state.set_state(Form.waiting_for_input)
    await state.update_data(action="expense")
    await callback.answer()


@router.message(Form.waiting_for_input)
async def process_input(message: Message, state: FSMContext):
    data = await state.get_data()
    action = data.get("action")
    text = message.text

    try:
        parts = [p.strip() for p in text.split(",")]
        if action == "sale":
            item_name = parts[0]
            qty = float(parts[1])
            # فرض قیمت پیش‌فرض هر آیتم برای تست
            price = qty * 100000
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO sales (item_name, qty, total_price) VALUES (?, ?,"
                " ?)",
                (item_name, qty, price),
            )
            conn.commit()
            conn.close()
            await message.answer(
                f"✅ فروش `{qty} عدد {item_name}` با موفقیت ثبت شد!",
                reply_markup=main_menu(),
                parse_mode="Markdown",
            )
        elif action == "expense":
            title = parts[0]
            amount = float(parts[1])
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO expenses (title, amount) VALUES (?, ?)",
                (title, amount),
            )
            conn.commit()
            conn.close()
            await message.answer(
                f"✅ هزینه `{title}` به مبلغ `{amount:,.0f}` تومان ثبت شد!",
                reply_markup=main_menu(),
                parse_mode="Markdown",
            )
    except Exception as e:
        await message.answer(
            "❌ فرمت وارد شده صحیح نیست. لطفاً مجدد تلاش کنید یا /start را بزنید."
        )

    await state.clear()


# وب‌سرور کوچک برای راضی نگه داشتن Render
async def handle_web(request):
    return web.Response(text="MoRe Coffee Bot is running!")


async def web_server():
    app = web.Application()
    app.router.add_get("/", handle_web)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 10000)
    await site.start()


async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    # اجرای همزمان ربات تلگرام و وب‌سرور
    await web_server()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
