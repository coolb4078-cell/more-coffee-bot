import os, io, asyncio, sqlite3
from pathlib import Path
from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, KeyboardButton, ReplyKeyboardMarkup, BufferedInputFile,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
import config

DB = Path(__file__).with_name(config.DB_PATH)

MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💰 ثبت فروش"), KeyboardButton(text="📊 گزارش")],
        [KeyboardButton(text="📦 لیست منو"), KeyboardButton(text="🧮 موجودی انبار")],
        [KeyboardButton(text="💸 ثبت هزینه"), KeyboardButton(text="📤 خروجی Excel")]
    ],
    resize_keyboard=True
)

# لیست تمام آیتم‌های استخراج شده از عکس‌های منوی کافه مور
INITIAL_MENU = {
    "نوشیدنی گرم بر پایه قهوه": [
        ("اسپرسو سینگل", 160000), ("اسپرسو دوبل", 180000), ("اسپرسو سینامون", 190000),
        ("اسپرسو ماکیاتو", 185000), ("کاپوچینو", 210000), ("لاته", 230000),
        ("لاته طعم‌دار", 255000), ("آمریکانو", 205000), ("موکا", 255000),
        ("فلت وایت", 210000), ("کورتادو", 190000), ("کارامل ماکیاتو", 255000),
    ],
    "سرد بر پایه قهوه": [
        ("آیس لاته", 250000), ("آیس موکا", 270000), ("آیس کارامل ماکیاتو", 270000),
        ("آیس آمریکانو", 210000), ("آیس لاته طعم‌دار", 270000),
    ],
    "هات‌نوش و ترکیبی": [
        ("قهوه ترک", 180000), ("قهوه یونانی", 195000), ("وانیلا گریک", 205000),
        ("پرشین", 235000), ("هات چاکلت", 210000), ("وایت چاکلت", 210000),
        ("پینک چاکلت", 210000), ("چای ماسالا", 200000), ("چای کرک", 210000),
    ],
    "چای و دمنوش": [
        ("چای سیاه", 100000), ("دمنوش گل‌گاو‌زبان", 155000), ("دمنوش چای ترش", 160000),
        ("دمنوش عناب و آویشن", 155000), ("دمنوش بابونه", 155000), ("دمنوش لاغری", 155000),
        ("دمنوش چای سبز", 160000), ("دمنوش ویتامین سی", 155000),
    ],
    "سرد بر پایه چای و میوه‌ای": [
        ("آیس کرنبری", 190000), ("آیس توت‌فرنگی", 190000), ("آیس نارگیل", 190000),
        ("آیس فندق", 190000), ("آیس وانیل", 190000), ("آیس میکس", 200000),
        ("آیس چاکلت", 200000), ("آب هویج", 140000), ("شیک نوتلا", 220000),
    ],
    "کیک و دسر": [
        ("کیک گردویی", 130000), ("کوکی شکلاتی", 130000), ("کوکی پسته", 150000),
        ("پروتئین بار", 130000), ("کوکی براونی", 200000), ("کیک شکلاتی", 270000),
        ("تارت پای سیب", 280000), ("براونی", 250000), ("تیرامیسو", 295000),
        ("بادام تفت داده", 200000),
    ]
}

def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c

def setup():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, category_id INTEGER REFERENCES categories(id), price REAL NOT NULL DEFAULT 0, stock REAL NOT NULL DEFAULT 999, unit TEXT NOT NULL DEFAULT 'عدد');
        CREATE TABLE IF NOT EXISTS sales(id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER REFERENCES items(id), quantity REAL, unit_price REAL, total REAL, created_at TEXT);
        CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, amount REAL, created_at TEXT);
        CREATE TABLE IF NOT EXISTS stock_log(id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER REFERENCES items(id), delta REAL, note TEXT, created_at TEXT);
        """)
        if c.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
            for cat_name, items_list in INITIAL_MENU.items():
                c.execute("INSERT OR IGNORE INTO categories(name) VALUES(?)", (cat_name,))
                cat_id = c.execute("SELECT id FROM categories WHERE name=?", (cat_name,)).fetchone()[0]
                for item_name, price in items_list:
                    c.execute("INSERT INTO items(name, category_id, price, stock, unit) VALUES(?,?,?,?,?)", (item_name, cat_id, price, 999, "عدد"))

def is_admin(user_id: int): return (not config.ADMIN_IDS) or (user_id in config.ADMIN_IDS)
def tm(): return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def kb_categories():
    with db() as c: cats = c.execute("SELECT id, name FROM categories ORDER BY id").fetchall()
    kb = [[InlineKeyboardButton(text=f"📂 {cat['name']}", callback_data=f"cat:{cat['id']}")] for cat in cats]
    kb.append([InlineKeyboardButton(text="❌ انصراف", callback_data="cancel_sale")]); return InlineKeyboardMarkup(inline_keyboard=kb)

def kb_items_by_cat(cat_id: int):
    with db() as c: items = c.execute("SELECT id, name, price FROM items WHERE category_id=?", (cat_id,)).fetchall()
    kb = [[InlineKeyboardButton(text=f"{item['name']} | {int(item['price']):,} ت", callback_data=f"item:{item['id']}")] for item in items]
    kb.append([InlineKeyboardButton(text="🔙 بازگشت به دسته‌ها", callback_data="back_to_cats")]); return InlineKeyboardMarkup(inline_keyboard=kb)

def kb_quantity(item_id: int):
    kb = [[InlineKeyboardButton(text=f"{n} عدد", callback_data=f"qty:{item_id}:{n}") for n in [1, 2, 3]],
          [InlineKeyboardButton(text=f"{n} عدد", callback_data=f"qty:{item_id}:{n}") for n in [4, 5]],
          [InlineKeyboardButton(text="✍️ تعداد دیگر", callback_data=f"custom_qty:{item_id}")],
          [InlineKeyboardButton(text="🔙 بازگشت", callback_data="back_to_cats")]]
    return InlineKeyboardMarkup(inline_keyboard=kb)

class S(StatesGroup): qty = State(); exp = State()

async def handle_ping(request): return web.Response(text="MoRe Coffee Bot is Live!")
async def start_webserver():
    app = web.Application(); app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080))).start()

async def start_cmd(m: Message):
    if is_admin(m.from_user.id): await m.answer("☕ خوش آمدید به پنل مدیریت MoRe Coffee", reply_markup=MENU)

async def start_sale(m: Message):
    if is_admin(m.from_user.id): await m.answer("📋 دسته را انتخاب کنید:", reply_markup=kb_categories())

async def sale_callbacks(cb: CallbackQuery, state: FSMContext):
    d = cb.data
    if d == "cancel_sale": await cb.message.edit_text("❌ لغو شد.")
    elif d == "back_to_cats": await cb.message.edit_text("📋 دسته را انتخاب کنید:", reply_markup=kb_categories())
    elif d.startswith("cat:"): await cb.message.edit_text("☕ کالا را انتخاب کنید:", reply_markup=kb_items_by_cat(int(d.split(":")[1])))
    elif d.startswith("item:"):
        with db() as c: it = c.execute("SELECT name, price FROM items WHERE id=?", (int(d.split(":")[1]),)).fetchone()
        await cb.message.edit_text(f"☕ <b>{it['name']}</b>\nقیمت: {int(it['price']):,} ت\nتعداد:", reply_markup=kb_quantity(int(d.split(":")[1])), parse_mode="HTML")
    elif d.startswith("qty:"):
        _, i_id, q = d.split(":"); i_id, q = int(i_id), float(q)
        with db() as c:
            it = c.execute("SELECT name, price FROM items WHERE id=?", (i_id,)).fetchone()
            tot = q * it['price']
            c.execute("UPDATE items SET stock=stock-? WHERE id=?", (q, i_id))
            c.execute("INSERT INTO sales(item_id,quantity,unit_price,total,created_at) VALUES(?,?,?,?,?)", (i_id, q, it['price'], tot, tm()))
        await cb.message.edit_text(f"✅ ثبت شد: {it['name']}\nتعداد: {int(q)}\nجمع: <b>{int(tot):,} تومان</b>", parse_mode="HTML")
    elif d.startswith("custom_qty:"):
        await state.update_data(i_id=int(d.split(":")[1])); await state.set_state(S.qty)
        await cb.message.edit_text("تعداد را وارد کنید:")
    await cb.answer()

async def receive_qty(m: Message, state: FSMContext):
    try:
        q = float(m.text.strip())
        data = await state.get_data(); i_id = data['i_id']
        with db() as c:
            it = c.execute("SELECT name, price FROM items WHERE id=?", (i_id,)).fetchone()
            tot = q * it['price']
            c.execute("UPDATE items SET stock=stock-? WHERE id=?", (q, i_id))
            c.execute("INSERT INTO sales(item_id,quantity,unit_price,total,created_at) VALUES(?,?,?,?,?)", (i_id, q, it['price'], tot, tm()))
        await state.clear(); await m.answer(f"✅ ثبت شد: {it['name']}\nتعداد: {q:g}\nجمع: {int(tot):,} ت", reply_markup=MENU)
    except: await m.answer("عدد نامعتبر!")

async def list_items(m: Message):
    with db() as c: rows = c.execute("SELECT i.name, i.price, c.name as cat FROM items i JOIN categories c ON i.category_id=c.id ORDER BY c.id").fetchall()
    res = "📋 <b>منوی فعلی:</b>\n"
    for r in rows: res += f"• {r['name']}: {int(r['price']):,} ت\n"
    await m.answer(res, parse_mode="HTML")

async def report_cmd(m: Message):
    with db() as c:
        s = c.execute("SELECT SUM(total) FROM sales").fetchone()[0] or 0
        e = c.execute("SELECT SUM(amount) FROM expenses").fetchone()[0] or 0
    await m.answer(f"📊 <b>گزارش:</b>\nفروش: {int(s):,} ت\nهزینه: {int(e):,} ت\nسود: {int(s-e):,} ت", parse_mode="HTML")

async def expense_cmd(m: Message, state: FSMContext):
    await state.set_state(S.exp); await m.answer("شرح هزینه | مبلغ (مثلاً: شیر | 50000)")

async def receive_exp(m: Message, state: FSMContext):
    try:
        t, a = m.text.split('|'); a = float(a.strip())
        with db() as c: c.execute("INSERT INTO expenses(title,amount,created_at) VALUES(?,?,?)", (t.strip(), a, tm()))
        await state.clear(); await m.answer("✅ ثبت شد.", reply_markup=MENU)
    except: await m.answer("قالب اشتباه!")

async def export_excel(m: Message):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = "Sales"
    ws.append(['کالا', 'تعداد', 'قیمت واحد', 'جمع', 'زمان'])
    with db() as c:
        for r in c.execute("SELECT i.name, s.quantity, s.unit_price, s.total, s.created_at FROM sales s JOIN items i ON i.id=s.item_id"):
            ws.append(list(r))
    buf = io.BytesIO(); wb.save(buf)
    await m.answer_document(BufferedInputFile(buf.getvalue(), filename="More_Report.xlsx"))

async def main():
    setup(); await start_webserver()
    bot = Bot(token=config.BOT_TOKEN); dp = Dispatcher()
    dp.message.register(start_cmd, CommandStart())
    dp.message.register(start_sale, F.text == "💰 ثبت فروش")
    dp.message.register(list_items, F.text == "📦 لیست منو")
    dp.message.register(report_cmd, F.text == "📊 گزارش")
    dp.message.register(expense_cmd, F.text == "💸 ثبت هزینه")
    dp.message.register(export_excel, F.text == "📤 خروجی Excel")
    dp.callback_query.register(sale_callbacks)
    dp.message.register(receive_qty, S.qty)
    dp.message.register(receive_exp, S.exp)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
