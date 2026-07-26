# Xodimlar va topshiriqlar Telegram boti

Aiogram 3 asosidagi bot: user arizasi, admin/manager tasdig‘i, guruhlarni ro‘yxatdan o‘tkazish va tanlangan xodimlarga topshiriq yuborish.

## Ishga tushirish

1. Python 3.11 yoki yangirog‘ini o‘rnating.
2. `.env.example` nusxasini `.env` nomi bilan saqlang.
3. `BOT_TOKEN` va `SUPERADMIN_IDS` qiymatlarini kiriting.
4. `pip install -r requirements.txt`
5. `python bot.py`

## Supabase

Server almashtirilganda ma’lumotlar yo‘qolmasligi uchun `.env` ichiga Supabase Dashboard → Connect bo‘limidagi **Session pooler** `DATABASE_URL` qiymatini kiriting. `DATABASE_URL` mavjud bo‘lsa bot Supabase Postgres’dan foydalanadi; bo‘lmasa lokal `bot.db` rejimida ishlaydi. Maxfiy ulanish satrini Git’ga joylamang.

Supabase sxemasi `supabase/migrations/0001_initial_schema.sql` faylida saqlanadi. Jadvallar yopiq `bot_app` sxemasida, RLS yoqilgan va `anon` hamda `authenticated` rollaridan ruxsatlar olib tashlangan.

Eski `bot.db` ma’lumotlarini bir marta ko‘chirish uchun `python migrate_to_supabase.py` buyrug‘ini ishlating. Migratsiya takror ishga tushirilsa mavjud yozuvlarni yangilaydi va dublikat yaratmaydi.

## Docker va Render

Lokal Docker tekshiruvi: `.env.render.example` nusxasini `.env` qilib maxfiy qiymatlarni kiriting, so‘ng `docker compose up --build` ishlating. Health manzili: `http://localhost:10000/health`.

Render uchun `render.yaml` tayyor. Repository GitHub/GitLab/Bitbucket’ga push qiling, Render’da Blueprint yarating va `BOT_TOKEN`, `SUPERADMIN_IDS`, `DATABASE_URL` secret qiymatlarini kiriting. Xizmat Docker web service sifatida `/health` endpoint bilan ishlaydi va Telegram polling faqat bitta instance’da bajariladi.

Botni guruhga qo‘shing va admin/manager nomidan `/register_group` yuboring. Yoki shaxsiy chatda `/add_group -100... Guruh nomi` orqali ID bilan qo‘shing.

Admin paneldagi user kartasidan userni manager qilish yoki manager rolini olib tashlash mumkin. `/set_manager TELEGRAM_ID` buyrug‘i ham ishlaydi. Har qanday formani `/cancel` bilan bekor qilish mumkin.

Topshiriq olgan user shaxsiy xabardagi `☑️ Bajardim` tugmasini bosadi. Bot guruh va topshiriq yaratuvchisiga xabar beradi. Admin va manager `📋 Topshiriqlar` bo‘limida tarix hamda har bir ijrochining holatini ko‘radi.

Topshiriq tafsilotidagi `🔔 Eslatma yuborish` tugmasi faqat hali bajarmagan ijrochilarni guruhda belgilaydi va ularning shaxsiy chatiga bajarish talabi hamda `☑️ Bajardim` tugmasini qayta yuboradi.

Admin panelda kutilayotgan arizalar alohida navbatda ko‘rinadi. Bosh admin user kartasidan manager rolini boshqarishi, userni vaqtincha bloklashi yoki qayta faollashtirishi hamda guruhni ro‘yxatdan olib tashlashi mumkin. Manager bu xavfli amallarni bajara olmaydi.

Superadmin `/start` da `Superadmin`, `Admin` yoki `User` rejimini tanlaydi. `🛡 Adminlar` bo‘limida Telegram ID orqali admin tayinlaydi yoki olib tashlaydi. `🎨 Tugma dizayni` bo‘limida Bot API qo‘llaydigan ko‘k, yashil yoki qizil uslubni va premium custom emoji ID’ni sozlaydi.

Har bir user arizani boshlaganda `Backend`, `Frontend`, `Full stack` yoki `Vibecoder` yo‘nalishidan birini tugma orqali majburiy tanlaydi. Tanlovsiz forma davom etmaydi. Yo‘nalish ariza, user kartasi va topshiriq uchun ijrochi tanlash tugmalarida ko‘rinadi.

Superadmin tanlagan global tugma rangi va premium emoji bosh menyu, inline amallar, sahifalash, ariza, admin, guruh, topshiriq va eslatma tugmalarining barchasiga qo‘llanadi.

Eslatma: user botga kamida bir marta `/start` yuborishi kerak; aks holda Telegram bot unga shaxsiy xabar jo‘nata olmaydi.
