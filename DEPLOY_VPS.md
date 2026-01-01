# 🌙 Tarot Luna — Полная инструкция по запуску на VPS

## 🔄 КРИТИЧЕСКОЕ ОБНОВЛЕНИЕ (30.12.2024) — ИСПРАВЛЕНИЕ ОПЛАТЫ!

### 🐛 ГЛАВНАЯ ПРОБЛЕМА БЫЛА:
**Колонка `yoomoney_label` не существовала в таблице `payments`** — миграция падала молча!

Из-за этого:
- `create_pending_payment()` не мог вставить запись (ошибка SQL)
- Scheduler не находил pending payments ("📭 No pending payments in database")
- Оплата не начислялась

### ✅ Что исправлено:
1. **database.py** — улучшена миграция колонок с логами и проверкой
2. **database.py** — `get_pending_payments()` теперь проверяет колонку
3. **database.py** — `create_pending_payment()` проверяет/добавляет колонку
4. **Profile.tsx** — ещё более компактные элементы

### 1. Загрузите обновленные файлы через SFTP:

**Backend (`/root/tarot-luna/backend/`):**
- `database.py` — **КРИТИЧНО!** Исправленные миграции
- `api.py`
- `config.py`
- `yoomoney.py`
- `main.py`

**Frontend (пересобирается через npm run build):**
- `src/pages/Profile.tsx`
- `src/pages/History.tsx`

### 2. ВАЖНО: Пересоздайте миграции на сервере:
```bash
cd /root/tarot-luna/backend
source venv/bin/activate

# Проверьте колонки в таблице payments
sqlite3 database.db ".schema payments"

# Если нет yoomoney_label — добавьте вручную:
sqlite3 database.db "ALTER TABLE payments ADD COLUMN yoomoney_label TEXT;"
sqlite3 database.db "ALTER TABLE payments ADD COLUMN yoomoney_operation_id TEXT;"
sqlite3 database.db "ALTER TABLE payments ADD COLUMN amount_received REAL;"

# Проверьте снова
sqlite3 database.db "PRAGMA table_info(payments);"
# Должны быть колонки: id, user_id, amount, requests, status, screenshot_id, timestamp, yoomoney_label, ...
```

### 3. Перезапустите backend:
```bash
pm2 restart tarot-backend
```

### 4. Пересоберите frontend:
```bash
cd /root/tarot-luna
npm run build
systemctl restart nginx
```

### 5. Проверка после обновления:
```bash
# Смотрите логи при создании платежа
tail -f /root/tarot-luna/backend/logs/bot.log | grep -E "payment|Payment|pending"

# Должно появиться:
# 💾 Inserting pending payment: user=..., amount=..., requests=..., label=...
# ✅ Created pending payment 1 for user ...

# Проверьте pending платежи в БД
sqlite3 /root/tarot-luna/backend/database.db "SELECT id, user_id, amount, yoomoney_label, status FROM payments WHERE status='pending';"
```

### 6. Тестовая покупка:
1. Откройте мини-приложение → Магазин
2. Выберите "🧪 Тестовый" (2 руб., 5 запросов)
3. Оплатите
4. Проверьте логи:
   ```bash
   grep "pending payment" /root/tarot-luna/backend/logs/bot.log | tail -5
   grep "Starting YooMoney" /root/tarot-luna/backend/logs/yoomoney.log | tail -5
   ```
5. Через 45-90 секунд должно появиться:
   ```
   ✅ Payment confirmed for user ...
   ```

### 7. Если платёж всё ещё не работает:
```bash
# 1. Проверьте колонки
sqlite3 database.db "PRAGMA table_info(payments);"

# 2. Проверьте есть ли pending
sqlite3 database.db "SELECT * FROM payments WHERE status='pending';"

# 3. Проверьте логи ошибок
grep -i "error\|Error\|CRITICAL" /root/tarot-luna/backend/logs/bot.log | tail -30

# 4. Если колонки нет — добавьте вручную (см. выше)
```

---


## 📋 Что нужно:
- VPS с Ubuntu 24.04 (IP: 185.105.91.173)
- Домен (например: tarotluna.mooo.com)
- Доступ по SSH (MobaXterm)

---

## 🚀 ШАГ 1: Настройка DNS (КРИТИЧЕСКИ ВАЖНО!)

### Если используете FreeDNS (freedns.afraid.org):
1. Зайдите на https://freedns.afraid.org
2. Войдите в аккаунт
3. Перейдите в **Subdomains** → найдите ваш домен
4. Убедитесь что **Destination** = `185.105.91.173`
5. Сохраните

### Проверка DNS (подождите 5-10 минут):
```bash
# На любом компьютере:
nslookup tarotluna.mooo.com
# Должен вернуть: 185.105.91.173

# Или онлайн: https://dnschecker.org
```

⚠️ **ВАЖНО:** Пока `dig tarotluna.mooo.com +short` не вернёт IP — сайт НЕ БУДЕТ работать!

---

## 🚀 ШАГ 2: Подключение к VPS

```bash
ssh root@185.105.91.173
```

---

## 🚀 ШАГ 3: Установка всех зависимостей

Выполните ВСЁ одной командой:

```bash
apt update && apt upgrade -y && \
apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx curl git && \
curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
apt install -y nodejs && \
npm install -g pm2
```

### Проверка:
```bash
python3 --version  # 3.12+
node --version     # v20+
pm2 --version      # 6+
nginx -v           # nginx/1.24+
```

---

## 🚀 ШАГ 4: Загрузка проекта

### Через SFTP (MobaXterm):
1. В MobaXterm нажмите **Session** → **SFTP**
2. Remote host: `185.105.91.173`, Username: `root`
3. Загрузите весь проект в `/root/tarot-luna/`

Структура должна быть:
```
/root/tarot-luna/
├── backend/
│   ├── main.py
│   ├── api.py
│   ├── database.py
│   ├── handlers.py
│   ├── config.py
│   ├── requirements.txt
│   └── ...
├── src/
├── public/
├── package.json
└── ...
```

---

## 🚀 ШАГ 5: Настройка Backend

```bash
cd /root/tarot-luna/backend

# Создаём виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# Устанавливаем зависимости
pip install --upgrade pip
pip install -r requirements.txt

# Создаём папки для базы и логов
mkdir -p database logs
```

### Создаём .env файл:
```bash
nano .env
```

Вставьте (замените на свои значения):
```env
# Telegram Bot
BOT_TOKEN=ВАШ_ТОКЕН_БОТА
ADMIN_ID=ВАШ_TELEGRAM_ID
BOT_USERNAME=TarotLunaSunBot

# Платежи
ADMIN_CARD_NUMBER=0000 0000 0000 0000
CARD_NUMBER=0000 0000 0000 0000

# OhMyGPT API
OHMYGPT_API_KEY=sk-ваш-ключ

# База данных
DB_PATH=database/tarot.db
LOG_PATH=logs/bot.log

# YooMoney (если используете)
YOOMONEY_BOT_TOKEN=ваш_токен
YOOMONEY_WALLET=ваш_кошелек
YOOMONEY_WEBHOOK_ENABLED=false

# API Server
API_HOST=0.0.0.0
API_PORT=8080

# Webapp URL для Mini App
WEBAPP_URL=https://tarotluna.mooo.com
```

Сохраните: `Ctrl+O`, `Enter`, `Ctrl+X`

### Запуск backend через PM2:
```bash
cd /root/tarot-luna/backend
source venv/bin/activate

# Останавливаем старый процесс (если есть)
pm2 delete tarot-backend 2>/dev/null

# Запускаем
pm2 start main.py --name tarot-backend --interpreter /root/tarot-luna/backend/venv/bin/python

# Проверяем статус
pm2 status

# Смотрим логи (Ctrl+C для выхода)
pm2 logs tarot-backend --lines 50

# Сохраняем для автозапуска
pm2 save
pm2 startup
```

Если статус **online** и нет ошибок — backend работает!

### Проверка API:
```bash
curl http://localhost:8080/api/health
```

---

## 🚀 ШАГ 6: Сборка Frontend

```bash
cd /root/tarot-luna

# Устанавливаем зависимости
npm install

# Создаём .env.production с правильным URL API
# ВАЖНО: Замените tarotluna.mooo.com на ваш домен!
echo 'VITE_API_URL=https://tarotluna.mooo.com' > .env.production

# Собираем проект
npm run build

# Проверяем что dist создался
ls -la dist/
```

После сборки появится папка `dist/` с готовыми файлами.

---

## 🚀 ШАГ 7: Настройка Nginx

### Удаляем дефолтный конфиг:
```bash
rm -f /etc/nginx/sites-enabled/default
```

### Создаём конфиг для сайта:
```bash
nano /etc/nginx/sites-available/tarot-luna
```

Вставьте (замените `tarotluna.mooo.com` на ваш домен):
```nginx
server {
    listen 80;
    server_name tarotluna.mooo.com;

    # Frontend (статические файлы)
    root /root/tarot-luna/dist;
    index index.html;

    # Для React Router (SPA)
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Прокси для API (backend)
    location /api/ {
        proxy_pass http://127.0.0.1:8080/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # CORS headers
        add_header Access-Control-Allow-Origin * always;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS, PUT, DELETE" always;
        add_header Access-Control-Allow-Headers "Content-Type, Authorization, X-Requested-With, X-Telegram-Init-Data" always;
        
        if ($request_method = 'OPTIONS') {
            return 204;
        }
    }

    # Кеширование статики
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

Сохраните: `Ctrl+O`, `Enter`, `Ctrl+X`

### Активируем конфиг:
```bash
ln -sf /etc/nginx/sites-available/tarot-luna /etc/nginx/sites-enabled/

# Даём права на папку dist
chmod -R 755 /root/tarot-luna/dist/
chmod 755 /root
chmod 755 /root/tarot-luna

# Проверяем синтаксис
nginx -t

# Перезапускаем nginx
systemctl restart nginx
systemctl enable nginx
```

---

## 🚀 ШАГ 8: Открываем порты

```bash
# Если используется ufw:
ufw allow 22
ufw allow 80
ufw allow 443
ufw --force enable
ufw status
```

---

## 🚀 ШАГ 9: Проверка работы (HTTP)

### Сначала проверьте DNS:
```bash
dig tarotluna.mooo.com +short
# Должен вернуть: 185.105.91.173
```

### Если DNS работает — проверьте в браузере:
```
http://tarotluna.mooo.com
```

Должна открыться страница приложения!

### Если страница пустая — проверьте:
```bash
# Есть ли файлы?
ls -la /root/tarot-luna/dist/

# Есть ли index.html?
cat /root/tarot-luna/dist/index.html | head -20

# Логи nginx
tail -20 /var/log/nginx/error.log
```

---

## 🚀 ШАГ 10: Получение SSL-сертификата (HTTPS)

⚠️ **DNS должен работать!** Проверьте: `dig tarotluna.mooo.com +short`

```bash
certbot --nginx -d tarotluna.mooo.com
```

1. Введите email
2. Согласитесь с условиями (Y)
3. Выберите редирект HTTP→HTTPS (вариант 2)

### Проверка:
```
https://tarotluna.mooo.com
```

Должен быть зелёный замок! 🔒

### Автопродление сертификата:
```bash
certbot renew --dry-run
```

---

## 🚀 ШАГ 11: Настройка Telegram BotFather

1. Откройте @BotFather в Telegram
2. Отправьте `/mybots`
3. Выберите вашего бота
4. **Bot Settings** → **Menu Button** → **Configure menu button**
5. Введите URL: `https://tarotluna.mooo.com`
6. Введите текст кнопки: `🔮 Открыть Tarot Luna`

---

## 🔧 Полезные команды

### Управление Backend:
```bash
pm2 status                    # Статус процессов
pm2 logs tarot-backend        # Логи в реальном времени
pm2 restart tarot-backend     # Перезапуск
pm2 stop tarot-backend        # Остановка
```

### Управление Nginx:
```bash
systemctl status nginx        # Статус
systemctl restart nginx       # Перезапуск
nginx -t                      # Проверка конфига
tail -f /var/log/nginx/error.log  # Логи ошибок
```

### Обновление проекта:
```bash
cd /root/tarot-luna

# Frontend
npm install
npm run build
systemctl restart nginx

# Backend
cd backend
source venv/bin/activate
pip install -r requirements.txt
pm2 restart tarot-backend
```

---

## 🐛 Решение проблем

### DNS не работает (dig возвращает пустоту):
1. Зайдите на freedns.afraid.org
2. Проверьте что Destination = 185.105.91.173
3. Подождите 10-30 минут
4. Попробуйте: `nslookup tarotluna.mooo.com 8.8.8.8`

### Пустая страница:
```bash
# Проверьте что dist существует и не пуст
ls -la /root/tarot-luna/dist/

# Проверьте права
chmod -R 755 /root/tarot-luna/dist/
chmod 755 /root
chmod 755 /root/tarot-luna

# Перезапустите nginx
systemctl restart nginx
```

### Backend не запускается:
```bash
cd /root/tarot-luna/backend
source venv/bin/activate

# Запуск вручную для просмотра ошибок
python main.py

# Если ошибка импорта — установите зависимости
pip install -r requirements.txt
```

### 502 Bad Gateway:
```bash
pm2 status
pm2 logs tarot-backend --lines 50
pm2 restart tarot-backend
```

---

## ✅ Чек-лист готовности

- [ ] DNS настроен: `dig tarotluna.mooo.com +short` = 185.105.91.173
- [ ] Backend работает: `pm2 status` = online
- [ ] Frontend собран: папка `dist/` существует
- [ ] Nginx работает: `systemctl status nginx`
- [ ] HTTP работает: http://tarotluna.mooo.com открывается
- [ ] HTTPS работает: https://tarotluna.mooo.com с замком
- [ ] BotFather настроен с HTTPS URL
- [ ] Mini App открывается в Telegram

---

## 📞 Если что-то не работает

Скопируйте вывод этих команд и пришлите мне:
```bash
dig tarotluna.mooo.com +short
pm2 status
pm2 logs tarot-backend --lines 30
nginx -t
ls -la /root/tarot-luna/dist/
curl http://localhost:8080/api/health
```

---

## 🔄 БЫСТРОЕ ОБНОВЛЕНИЕ (после последних исправлений 29.12.2024)

### 🐛 Исправленные баги:
1. **Толкование не соответствовало картам** — API теперь принимает карты от фронтенда
2. **История покупок не загружалась** — История теперь показывает платежи из БД
3. **Мобильная версия растянута** — Улучшена адаптивность карт и элементов

### Какие файлы загрузить:
Через SFTP загрузите в `/root/tarot-luna/`:

**Backend (в `/root/tarot-luna/backend/`):**
- `api.py` — КРИТИЧНО: принимает карты от фронтенда вместо генерации своих
- `database.py` — методы use_free_request, use_premium_request, get_user_stats
- `config.py` — WEBAPP_URL
- `handlers.py` — /start с кнопкой Web App
- `yoomoney.py` — полный файл из папки Luna

**Frontend (в `/root/tarot-luna/src/`):**
- `src/lib/api.ts` — передача карт на сервер
- `src/pages/Reading.tsx` — передача карт и мобильная адаптация
- `src/pages/History.tsx` — отображение платежей
- `src/components/TarotCard.tsx` — адаптивные размеры

### Команды на сервере:
```bash
# 1. Обновление backend
cd /root/tarot-luna/backend
source venv/bin/activate
pip install -r requirements.txt
pm2 restart tarot-backend

# 2. Проверка backend
pm2 logs tarot-backend --lines 20

# 3. ОБЯЗАТЕЛЬНО пересобрать frontend (были изменения!)
cd /root/tarot-luna
npm install
npm run build

# 4. Перезапуск nginx
systemctl restart nginx

# 5. Очистить кеш браузера или открыть в режиме инкогнито
```

### Быстрая проверка:
```bash
# Проверить backend
curl http://localhost:8080/api/health

# Проверить frontend
curl -I https://tarotluna.mooo.com
```

---

## 🛠️ Полный рестарт

Если что-то сломалось — полный рестарт всего:

```bash
# Остановить всё
pm2 stop all
systemctl stop nginx

# Backend
cd /root/tarot-luna/backend
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Frontend
cd /root/tarot-luna
rm -rf node_modules dist
npm install
npm run build

# Запустить
pm2 delete tarot-backend 2>/dev/null
pm2 start main.py --name tarot-backend --interpreter /root/tarot-luna/backend/venv/bin/python
pm2 save
systemctl start nginx

# Проверить
pm2 status
curl http://localhost:8080/api/health
```

🌙✨
