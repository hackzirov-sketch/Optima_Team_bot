# Optima Team Bot — V1 yakuniy reliz

Reliz sanasi: 2026-07-26  
Holat: **V1 feature freeze — yakunlangan va production uchun tayyor**

## V1 imkoniyatlari

- Superadmin, admin, manager va user rollari; superadmin uchun uch xil faol rejim.
- Ariza formasi: ism-familiya, yosh, yo‘nalish, telefon, portfolio (matn/link/PDF/DOCX) va erkin tavsif.
- Ariza 24 soatlik qayta topshirish cheklovi va pending/accepted takroriy yuborish himoyasi.
- Yangi arizalarni barcha mas’ullarga bevosita yuborish, bitta qarordan so‘ng barcha xabarlarni sinxron yangilash.
- Qabul/rad qaroridan keyin admin izohi va qaror audit ma’lumotlari.
- Admin, manager va dasturchilar bo‘yicha alohida jamoa ro‘yxatlari; superadmin maxfiyligi.
- Bitta yoki bir nechta userga guruh va shaxsiy chat orqali topshiriq yuborish.
- Topshiriq holatlari, natija fayllari, qayta ishlash, 1–5 baholash va guruh xabarini yangilash.
- Userdan topshiriq muallifiga savol yuborish va bot ichida javob qaytarish.
- Qo‘lda va avtomatik eslatmalar; userlarni Telegram mention orqali belgilash.
- Kengaytirilgan statistika: bajarilish, kechikish, o‘rtacha vaqt, reyting, yo‘nalish va user kesimi.
- Superadmin boshqaruvi: admin tayinlash/olib tashlash, xavfli amallar uchun tasdiqlash oynalari.
- Barcha tugmalar ranglari va Premium emoji dizayni.
- Xabarlardagi oddiy/Premium emojilar va asosiy xabar shablonlarini botsiz kod o‘zgartirmasdan sozlash.
- `/status` orqali Supabase, uptime, user va pending ariza holatini ko‘rish.
- Kutilmagan xatolarni superadminlarga Telegram orqali avtomatik bildirish.
- Audit jurnali, qidiruv, shablonlar, portfolio ma’lumotnomasi va guruh boshqaruvi.

## Ma’lumotlar va backup

- Production ma’lumotlari Supabase Postgres’dagi yopiq `bot_app` sxemasida saqlanadi.
- Yangi jadvallarda RLS yoqilgan; `anon` va `authenticated` rollariga kirish berilmagan.
- Supabase loyihalari uchun platformaning boshqariladigan kundalik backup siyosati qo‘llanadi. Muhim production davrida Supabase Dashboard → Database → Backups orqali oxirgi backup holatini muntazam tekshirish kerak.
- Katta relizdan oldin qo‘shimcha mantiqiy `pg_dump` nusxasi olish, pullik rejada esa PITR’ni yoqish tavsiya etiladi.
- Barcha sxema o‘zgarishlari `supabase/migrations/` ichida versiyalangan.

## Deploy

- GitHub: `hackzirov-sketch/Optima_Team_bot`
- Branch: `main`
- Hosting: Render, Docker runtime
- Health endpoint: `/health`
- Doimiy baza: Supabase Postgres

## Feature freeze

V1 yakunlangan. Bundan keyin bir muddat yangi funksiya qo‘shilmaydi. Faqat quyidagilar zarur bo‘lsa o‘zgartirish kiritiladi:

1. production xatosi yoki xavfsizlik muammosi;
2. Telegram/Supabase/Render tomonidan majburiy API o‘zgarishi;
3. ma’lumot yo‘qolishiga olib kelishi mumkin bo‘lgan muammo.

Keyingi katta funksiyalar V2 rejasiga yig‘iladi.
