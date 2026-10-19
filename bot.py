import asyncio, sqlite3, io
from pathlib import Path
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, BufferedInputFile
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
import config
DB=Path(__file__).with_name(config.DB_PATH)
class S(StatesGroup): cat=State(); item=State(); stock=State(); recipe=State(); sale=State(); expense=State()
MENU=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=t) for t in row] for row in [['📁 دسته‌بندی‌ها','➕ دسته‌بندی'],['📦 کالاها','➕ کالای جدید'],['🧮 موجودی','✏️ تغییر موجودی'],['🧾 دستور ساخت','➕ ثبت دستور ساخت'],['💰 ثبت فروش','💸 ثبت هزینه'],['📊 گزارش','📤 خروجی Excel']]],resize_keyboard=True)
def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c
def setup():
 with db() as c: c.executescript("CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY,name TEXT UNIQUE NOT NULL); CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY,name TEXT NOT NULL,category_id INTEGER REFERENCES categories(id),price REAL NOT NULL DEFAULT 0,stock REAL NOT NULL DEFAULT 0,unit TEXT NOT NULL DEFAULT 'عدد'); CREATE TABLE IF NOT EXISTS recipes(id INTEGER PRIMARY KEY,product_id INTEGER REFERENCES items(id) ON DELETE CASCADE,ingredient_id INTEGER REFERENCES items(id),quantity REAL NOT NULL,UNIQUE(product_id,ingredient_id)); CREATE TABLE IF NOT EXISTS sales(id INTEGER PRIMARY KEY,item_id INTEGER REFERENCES items(id),quantity REAL,unit_price REAL,total REAL,created_at TEXT); CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY,title TEXT,amount REAL,created_at TEXT); CREATE TABLE IF NOT EXISTS stock_log(id INTEGER PRIMARY KEY,item_id INTEGER REFERENCES items(id),delta REAL,note TEXT,created_at TEXT);")
def ok(m): return m.from_user.id in config.ADMIN_IDS
def tm(): return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
def n(x): return float(x.replace(',','.'))
async def no(m): await m.answer('⛔ دسترسی فقط برای مدیران مجاز است.')
async def begin(m,s,state,prompt):
 if not ok(m): return await no(m)
 await s.set_state(state); await m.answer(prompt+'\nلغو: /cancel')
async def cancel(m,s): await s.clear(); await m.answer('لغو شد.',reply_markup=MENU)
async def start(m):
 if not ok(m): return await no(m)
 await m.answer('☕ سامانه مدیریت MoRe Coffee',reply_markup=MENU)
async def cats(m):
 if not ok(m): return await no(m)
 with db() as c: rows=c.execute('SELECT id,name FROM categories ORDER BY name').fetchall()
 await m.answer('📁 دسته‌بندی‌ها:\n'+('\n'.join(f"{x['id']} — {x['name']}" for x in rows) or 'خالی'),reply_markup=MENU)
async def cat0(m,s): await begin(m,s,S.cat,'نام دسته را بفرستید:')
async def cat1(m,s):
 try:
  with db() as c: c.execute('INSERT INTO categories(name) VALUES(?)',(m.text.strip(),))
  await s.clear(); await m.answer('✅ ثبت شد.',reply_markup=MENU)
 except sqlite3.IntegrityError: await m.answer('نام تکراری است؛ نام دیگری بفرستید.')
async def items(m):
 if not ok(m): return await no(m)
 with db() as c: rows=c.execute('SELECT i.*,COALESCE(g.name,"بدون دسته") cat FROM items i LEFT JOIN categories g ON g.id=i.category_id').fetchall()
 await m.answer('📦 کالاها:\n'+('\n'.join(f"{x['id']} — {x['name']} | {x['cat']} | قیمت {x['price']:g} | موجودی {x['stock']:g} {x['unit']}" for x in rows) or 'خالی'),reply_markup=MENU)
async def item0(m,s):
 if not ok(m): return await no(m)
 with db() as c: rows=c.execute('SELECT id,name FROM categories').fetchall()
 await begin(m,s,S.item,'نام | شناسه دسته (0=بدون دسته) | قیمت | موجودی اولیه | واحد\n'+('\n'.join(f"{x['id']}={x['name']}" for x in rows) or 'دسته‌ای ثبت نشده'))
async def item1(m,s):
 try:
  name,cat,price,stock,unit=[x.strip() for x in m.text.split('|')]; cat=int(cat); price=n(price); stock=n(stock)
  if price<0 or stock<0 or not name: raise ValueError()
  with db() as c:
   c.execute('INSERT INTO items(name,category_id,price,stock,unit) VALUES(?,?,?,?,?)',(name,cat or None,price,stock,unit or 'عدد')); i=c.execute('SELECT last_insert_rowid()').fetchone()[0]
   if stock: c.execute('INSERT INTO stock_log(item_id,delta,note,created_at) VALUES(?,?,?,?)',(i,stock,'موجودی اولیه',tm()))
  await s.clear(); await m.answer('✅ کالا ثبت شد.',reply_markup=MENU)
 except (ValueError,sqlite3.IntegrityError): await m.answer('ورودی نامعتبر است؛ نمونه: لاته | 1 | 120000 | 10 | عدد')
async def inventory(m):
 if not ok(m): return await no(m)
 with db() as c: rows=c.execute('SELECT id,name,stock,unit FROM items').fetchall()
 await m.answer('🧮 موجودی:\n'+('\n'.join(f"{x['id']} — {x['name']}: {x['stock']:g} {x['unit']}" for x in rows) or 'خالی'),reply_markup=MENU)
async def stock0(m,s): await begin(m,s,S.stock,'شناسه کالا | مقدار تغییر (منفی=خروج) | توضیح')
async def stock1(m,s):
 try:
  p=m.text.split('|'); i=int(p[0]); d=n(p[1]); note=p[2].strip() if len(p)>2 else 'اصلاح دستی'
  with db() as c:
   x=c.execute('SELECT stock FROM items WHERE id=?',(i,)).fetchone()
   if not x: return await m.answer('شناسه کالا پیدا نشد.')
   if x['stock']+d<0: return await m.answer('موجودی منفی مجاز نیست.')
   c.execute('UPDATE items SET stock=stock+? WHERE id=?',(d,i)); c.execute('INSERT INTO stock_log(item_id,delta,note,created_at) VALUES(?,?,?,?)',(i,d,note,tm()))
  await s.clear(); await m.answer('✅ موجودی تغییر کرد.',reply_markup=MENU)
 except (ValueError,IndexError): await m.answer('قالب: شناسه | مقدار تغییر | توضیح')
async def recipes(m):
 if not ok(m): return await no(m)
 with db() as c: rows=c.execute('SELECT p.name pn,i.name inn,r.quantity,i.unit FROM recipes r JOIN items p ON p.id=r.product_id JOIN items i ON i.id=r.ingredient_id').fetchall()
 await m.answer('🧾 دستور ساخت (برای یک واحد):\n'+('\n'.join(f"{x['pn']} ← {x['quantity']:g} {x['unit']} {x['inn']}" for x in rows) or 'خالی'),reply_markup=MENU)
async def recipe0(m,s):
 if not ok(m): return await no(m)
 with db() as c: rows=c.execute('SELECT id,name FROM items').fetchall()
 await begin(m,s,S.recipe,'شناسه محصول | شناسه ماده اولیه | مقدار برای یک محصول\n'+('\n'.join(f"{x['id']} — {x['name']}" for x in rows) or 'کالایی نیست'))
async def recipe1(m,s):
 try:
  a,b,q=m.text.split('|'); a=int(a); b=int(b); q=n(q)
  if a==b or q<=0: raise ValueError()
  with db() as c: c.execute('INSERT INTO recipes(product_id,ingredient_id,quantity) VALUES(?,?,?) ON CONFLICT(product_id,ingredient_id) DO UPDATE SET quantity=excluded.quantity',(a,b,q))
  await s.clear(); await m.answer('✅ دستور ثبت شد.',reply_markup=MENU)
 except (ValueError,sqlite3.IntegrityError): await m.answer('ورودی یا شناسه نامعتبر است.')
async def sale0(m,s):
 if not ok(m): return await no(m)
 with db() as c: rows=c.execute('SELECT id,name,price FROM items').fetchall()
 await begin(m,s,S.sale,'شناسه کالا | تعداد\n'+('\n'.join(f"{x['id']} — {x['name']} (قیمت {x['price']:g})" for x in rows) or 'کالایی نیست'))
async def sale1(m,s):
 try:
  i,q=m.text.split('|'); i=int(i); q=n(q)
  if q<=0: raise ValueError()
  with db() as c:
   it=c.execute('SELECT * FROM items WHERE id=?',(i,)).fetchone()
   if not it: return await m.answer('کالا پیدا نشد.')
   rows=c.execute('SELECT ingredient_id,quantity FROM recipes WHERE product_id=?',(i,)).fetchall(); req=[(x['ingredient_id'],x['quantity']*q) for x in rows] or [(i,q)]
   for j,need in req:
    x=c.execute('SELECT name,stock FROM items WHERE id=?',(j,)).fetchone()
    if not x or x['stock']<need: return await m.answer(f"موجودی ناکافی: {x['name'] if x else j}")
   for j,need in req:
    c.execute('UPDATE items SET stock=stock-? WHERE id=?',(need,j)); c.execute('INSERT INTO stock_log(item_id,delta,note,created_at) VALUES(?,?,?,?)',(j,-need,'مصرف فروش '+it['name'],tm()))
   total=q*it['price']; c.execute('INSERT INTO sales(item_id,quantity,unit_price,total,created_at) VALUES(?,?,?,?,?)',(i,q,it['price'],total,tm()))
  await s.clear(); await m.answer(f'✅ فروش ثبت شد. مبلغ: {total:,.0f}',reply_markup=MENU)
 except (ValueError,IndexError): await m.answer('قالب: شناسه کالا | تعداد')
async def exp0(m,s): await begin(m,s,S.expense,'شرح هزینه | مبلغ')
async def exp1(m,s):
 try:
  title,amount=m.text.split('|'); amount=n(amount)
  if amount<=0 or not title.strip(): raise ValueError()
  with db() as c: c.execute('INSERT INTO expenses(title,amount,created_at) VALUES(?,?,?)',(title.strip(),amount,tm()))
  await s.clear(); await m.answer('✅ هزینه ثبت شد.',reply_markup=MENU)
 except (ValueError,IndexError): await m.answer('قالب: شرح هزینه | مبلغ')
async def report(m):
 if not ok(m): return await no(m)
 with db() as c: a=c.execute('SELECT COALESCE(SUM(total),0),COUNT(*) FROM sales').fetchone(); b=c.execute('SELECT COALESCE(SUM(amount),0),COUNT(*) FROM expenses').fetchone(); k=c.execute('SELECT COUNT(*) FROM items').fetchone()[0]
 await m.answer(f'📊 گزارش کل\nفروش: {a[0]:,.0f} ({a[1]} تراکنش)\nهزینه: {b[0]:,.0f} ({b[1]} مورد)\nفروش منهای هزینه: {a[0]-b[0]:,.0f}\nتعداد کالا: {k}',reply_markup=MENU)
async def export(m):
 if not ok(m): return await no(m)
 from openpyxl import Workbook
 from openpyxl.styles import Font,PatternFill
 w=Workbook(); w.remove(w.active); tables=[('کالاها','SELECT i.id,i.name,COALESCE(g.name,"-") category,i.price,i.stock,i.unit FROM items i LEFT JOIN categories g ON g.id=i.category_id',['شناسه','نام','دسته','قیمت','موجودی','واحد']),('فروش','SELECT s.id,i.name,s.quantity,s.unit_price,s.total,s.created_at FROM sales s JOIN items i ON i.id=s.item_id',['شناسه','کالا','تعداد','قیمت واحد','مبلغ کل','زمان']),('هزینه‌ها','SELECT id,title,amount,created_at FROM expenses',['شناسه','شرح','مبلغ','زمان']),('دسته‌ها','SELECT id,name FROM categories',['شناسه','نام']),('دستور ساخت','SELECT p.name,i.name,r.quantity,i.unit FROM recipes r JOIN items p ON p.id=r.product_id JOIN items i ON i.id=r.ingredient_id',['محصول','ماده اولیه','مقدار','واحد'])]
 with db() as c:
  for title,sql,heads in tables:
   ws=w.create_sheet(title); ws.append(heads)
   for row in c.execute(sql): ws.append(list(row))
   ws.freeze_panes='A2'; ws.auto_filter.ref=ws.dimensions
   for cell in ws[1]: cell.font=Font(bold=True,color='FFFFFF'); cell.fill=PatternFill('solid',fgColor='5B3A29')
   for col in ws.columns: ws.column_dimensions[col[0].column_letter].width=min(32,max(12,max(len(str(x.value or '')) for x in col)+2))
 b=io.BytesIO(); w.save(b); await m.answer_document(BufferedInputFile(b.getvalue(),filename='more_coffee_report.xlsx'),caption='گزارش MoRe Coffee')
async def main():
 setup()
 if not config.BOT_TOKEN: raise RuntimeError('توکن را در config.py تنظیم کنید')
 dp=Dispatcher(); bot=Bot(config.BOT_TOKEN); dp.message.register(cancel,Command('cancel')); dp.message.register(start,CommandStart())
 for fn,label in [(cats,'📁 دسته‌بندی‌ها'),(cat0,'➕ دسته‌بندی'),(items,'📦 کالاها'),(item0,'➕ کالای جدید'),(inventory,'🧮 موجودی'),(stock0,'✏️ تغییر موجودی'),(recipes,'🧾 دستور ساخت'),(recipe0,'➕ ثبت دستور ساخت'),(sale0,'💰 ثبت فروش'),(exp0,'💸 ثبت هزینه'),(report,'📊 گزارش'),(export,'📤 خروجی Excel')]: dp.message.register(fn,F.text==label)
 for fn,state in [(cat1,S.cat),(item1,S.item),(stock1,S.stock),(recipe1,S.recipe),(sale1,S.sale),(exp1,S.expense)]: dp.message.register(fn,state)
 await dp.start_polling(bot)
if __name__=='__main__': asyncio.run(main())
