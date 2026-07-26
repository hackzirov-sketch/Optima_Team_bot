FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=10000

WORKDIR /app

RUN addgroup --system bot && adduser --system --ingroup bot bot

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY --chown=bot:bot bot.py migrate_to_supabase.py README.md ./
COPY --chown=bot:bot supabase ./supabase

USER bot
EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','10000')+'/health',timeout=3)" || exit 1

CMD ["python", "bot.py"]
