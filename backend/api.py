"""
api.py
API эндпоинты для Telegram Mini App.
Интегрируется с существующим ботом через aiohttp.
"""

import hmac
import hashlib
import json
import logging
import urllib.parse
from typing import Optional, Dict, Any, Tuple
from datetime import datetime

from aiohttp import web

from config import BOT_TOKEN, ADMIN_ID, FORBIDDEN_KEYWORDS, PAYMENT_OPTIONS
from database import db

logger = logging.getLogger(__name__)

# ==================== ВЕРИФИКАЦИЯ TELEGRAM INITDATA ====================

def verify_telegram_init_data(init_data: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Верифицирует initData от Telegram Mini App по официальной документации.
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    
    Returns:
        Tuple[bool, Optional[Dict]]: (is_valid, parsed_data)
    """
    try:
        if not init_data:
            return False, None
        
        # Парсим query string
        parsed = urllib.parse.parse_qs(init_data)
        
        # Получаем hash из данных
        received_hash = parsed.get('hash', [None])[0]
        if not received_hash:
            logger.warning("No hash in initData")
            return False, None
        
        # Собираем data_check_string
        data_pairs = []
        for key, values in parsed.items():
            if key != 'hash':
                data_pairs.append(f"{key}={values[0]}")
        
        # Сортируем по алфавиту
        data_pairs.sort()
        data_check_string = '\n'.join(data_pairs)
        
        # Создаём secret key
        secret_key = hmac.new(
            b'WebAppData',
            BOT_TOKEN.encode('utf-8'),
            hashlib.sha256
        ).digest()
        
        # Вычисляем hash
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Сравниваем
        if not hmac.compare_digest(calculated_hash, received_hash):
            logger.warning(f"Hash mismatch: calculated={calculated_hash[:16]}... received={received_hash[:16]}...")
            return False, None
        
        # Проверяем auth_date (не старше 24 часов)
        auth_date_str = parsed.get('auth_date', [None])[0]
        if auth_date_str:
            auth_date = int(auth_date_str)
            now = int(datetime.now().timestamp())
            if now - auth_date > 86400:  # 24 часа
                logger.warning(f"Auth date too old: {now - auth_date} seconds")
                return False, None
        
        # Парсим user
        user_str = parsed.get('user', [None])[0]
        user_data = None
        if user_str:
            user_data = json.loads(user_str)
        
        return True, {
            'user': user_data,
            'auth_date': auth_date_str,
            'query_id': parsed.get('query_id', [None])[0],
            'chat_type': parsed.get('chat_type', [None])[0],
            'chat_instance': parsed.get('chat_instance', [None])[0],
        }
        
    except Exception as e:
        logger.error(f"Error verifying initData: {e}")
        return False, None


def get_user_id_from_request(request: web.Request) -> Optional[int]:
    """
    Извлекает user_id из заголовка X-Telegram-Init-Data.
    Для тестирования также принимает X-User-Id напрямую или из query params.
    """
    # Для production: верификация initData
    init_data = request.headers.get('X-Telegram-Init-Data', '')
    if init_data:
        is_valid, data = verify_telegram_init_data(init_data)
        if is_valid and data and data.get('user'):
            user_id = data['user'].get('id')
            logger.debug(f"Got user_id from initData: {user_id}")
            return user_id
    
    # Для тестирования: прямой user_id из заголовка
    user_id_header = request.headers.get('X-User-Id')
    if user_id_header:
        try:
            user_id = int(user_id_header)
            logger.debug(f"Got user_id from header: {user_id}")
            return user_id
        except ValueError:
            pass
    
    # Fallback: из query параметров (для GET запросов)
    user_id_query = request.query.get('user_id')
    if user_id_query:
        try:
            user_id = int(user_id_query)
            logger.debug(f"Got user_id from query: {user_id}")
            return user_id
        except ValueError:
            pass
    
    logger.warning("Could not extract user_id from request")
    return None


def check_forbidden_keywords(text: str) -> bool:
    """Проверяет текст на запрещённые слова."""
    if FORBIDDEN_KEYWORDS.search(text):
        return True
    return False


# ==================== CORS MIDDLEWARE ====================

def cors_headers() -> Dict[str, str]:
    """Возвращает CORS заголовки."""
    return {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, X-Telegram-Init-Data, X-User-Id, Authorization',
        'Access-Control-Max-Age': '3600',
    }


@web.middleware
async def cors_middleware(request: web.Request, handler):
    """CORS middleware для всех запросов."""
    if request.method == 'OPTIONS':
        return web.Response(status=200, headers=cors_headers())
    
    response = await handler(request)
    response.headers.update(cors_headers())
    return response


# ==================== API HANDLERS ====================

async def handle_auth(request: web.Request) -> web.Response:
    """
    POST /api/auth
    Верифицирует initData и возвращает данные пользователя.
    """
    try:
        body = await request.json()
        init_data = body.get('initData', '')
        
        # Верифицируем
        is_valid, data = verify_telegram_init_data(init_data)
        
        if not is_valid or not data or not data.get('user'):
            return web.json_response({
                'success': False,
                'error': 'Invalid initData'
            }, status=401, headers=cors_headers())
        
        user_tg = data['user']
        user_id = user_tg['id']
        
        # Получаем или создаём пользователя в БД
        user = await db.get_user(user_id)
        
        if not user:
            # Новый пользователь
            await db.add_user(
                user_id=user_id,
                username=user_tg.get('username', ''),
                first_name=user_tg.get('first_name', ''),
                last_name=user_tg.get('last_name', ''),
            )
            user = await db.get_user(user_id)
        
        # Получаем статистику
        stats = await db.get_user_stats(user_id)
        level_info = await db.get_user_level_info(user_id)
        achievements = await db.get_user_achievements(user_id)
        
        return web.json_response({
            'success': True,
            'user': {
                'id': user_id,
                'username': user.get('username'),
                'first_name': user.get('first_name'),
                'last_name': user.get('last_name'),
                'requests_left': user.get('requests_left', 0),
                'premium_requests': user.get('premium_requests', 0),
                'is_banned': user.get('is_banned', False),
                'agreed_rules': user.get('agreed_rules', False),
                'level': level_info.get('level', 1) if level_info else 1,
                'experience': level_info.get('experience', 0) if level_info else 0,
                'total_readings': stats.get('total_readings', 0) if stats else 0,
                'achievements_count': len(achievements),
            }
        }, headers=cors_headers())
        
    except Exception as e:
        logger.error(f"Auth error: {e}")
        return web.json_response({
            'success': False,
            'error': str(e)
        }, status=500, headers=cors_headers())


async def handle_get_user(request: web.Request) -> web.Response:
    """
    GET /api/user
    Возвращает данные текущего пользователя.
    """
    try:
        user_id = get_user_id_from_request(request)
        if not user_id:
            return web.json_response({
                'success': False,
                'error': 'Unauthorized'
            }, status=401, headers=cors_headers())
        
        user = await db.get_user(user_id)
        if not user:
            return web.json_response({
                'success': False,
                'error': 'User not found'
            }, status=404, headers=cors_headers())
        
        stats = await db.get_user_stats(user_id)
        level_info = await db.get_user_level_info(user_id)
        achievements = await db.get_user_achievements(user_id)
        
        return web.json_response({
            'success': True,
            'user': {
                'id': user_id,
                'username': user.get('username'),
                'first_name': user.get('first_name'),
                'last_name': user.get('last_name'),
                'requests_left': user.get('requests_left', 0),
                'premium_requests': user.get('premium_requests', 0),
                'referrals_count': user.get('referrals_count', 0),
                'is_banned': user.get('is_banned', False),
                'agreed_rules': user.get('agreed_rules', False),
                'level': level_info.get('level', 1) if level_info else 1,
                'total_readings': level_info.get('total_readings', 0) if level_info else 0,
            },
            'stats': stats or {},
            'level': level_info or {'level': 1, 'experience': 0},
            'achievements': achievements or [],
        }, headers=cors_headers())
        
    except Exception as e:
        logger.error(f"Get user error: {e}")
        return web.json_response({
            'success': False,
            'error': str(e)
        }, status=500, headers=cors_headers())


async def handle_reading(request: web.Request) -> web.Response:
    """
    POST /api/reading
    Создаёт новый расклад Таро.
    """
    try:
        user_id = get_user_id_from_request(request)
        if not user_id:
            return web.json_response({
                'success': False,
                'error': 'Unauthorized'
            }, status=401, headers=cors_headers())
        
        body = await request.json()
        question = body.get('question', '').strip()
        cards_count = body.get('cards_count', 3)
        reading_type = body.get('reading_type', 'classic')
        use_premium = body.get('use_premium', False)
        cards_from_frontend = body.get('cards', [])  # Карты от фронтенда
        
        # Валидация
        if not question:
            return web.json_response({
                'success': False,
                'error': 'Question is required'
            }, status=400, headers=cors_headers())
        
        if len(question) > 300:
            return web.json_response({
                'success': False,
                'error': 'Question too long (max 300 chars)'
            }, status=400, headers=cors_headers())
        
        # Проверка запрещённых слов
        if check_forbidden_keywords(question):
            # Увеличиваем счётчик нарушений
            await db.increment_forbidden_attempts(user_id)
            return web.json_response({
                'success': False,
                'error': 'forbidden_keywords',
                'message': 'Вопрос содержит запрещённые темы. Пожалуйста, избегайте вопросов о болезнях, смерти и других деликатных тем.'
            }, status=400, headers=cors_headers())
        
        # Проверяем баланс
        user = await db.get_user(user_id)
        if not user:
            return web.json_response({
                'success': False,
                'error': 'User not found'
            }, status=404, headers=cors_headers())
        
        requests_left = user.get('requests_left', 0)
        premium_requests = user.get('premium_requests', 0)
        
        if use_premium:
            if premium_requests <= 0:
                return web.json_response({
                    'success': False,
                    'error': 'no_premium_requests'
                }, status=400, headers=cors_headers())
        else:
            if requests_left <= 0:
                return web.json_response({
                    'success': False,
                    'error': 'no_free_requests'
                }, status=400, headers=cors_headers())
        
        # Импортируем функции генерации
        from utils import generate_tarot_cards
        from ohmygpt_api import get_tarot_response
        
        # Используем карты от фронтенда, если они есть, иначе генерируем
        if cards_from_frontend and len(cards_from_frontend) > 0:
            cards = cards_from_frontend
            logger.info(f"Using cards from frontend: {cards}")
        else:
            cards = generate_tarot_cards(cards_count)
            logger.info(f"Generated cards on backend: {cards}")
        
        # Получаем историю для контекста
        history = await db.get_history(user_id, limit=3)
        history_context = ""
        if history:
            for h in history:
                history_context += f"Вопрос: {h.get('question', '')}\nКарты: {h.get('cards', '')}\n\n"
        
        # Получаем ответ от AI
        response = await get_tarot_response(
            question=question,
            cards=cards,
            is_premium=use_premium,
            full_history=history_context,
            user_id=user_id,
            username=user.get('username', ''),
            reading_type=reading_type
        )
        
        if not response:
            return web.json_response({
                'success': False,
                'error': 'AI service unavailable'
            }, status=503, headers=cors_headers())
        
        # Извлекаем текст ответа
        interpretation = ""
        if response and 'choices' in response:
            interpretation = response['choices'][0]['message']['content']
        
        # Списываем запрос
        if use_premium:
            await db.use_premium_request(user_id)
        else:
            await db.use_free_request(user_id)
        
        # Сохраняем в историю
        await db.add_history(
            user_id=user_id,
            question=question,
            cards=json.dumps(cards, ensure_ascii=False),
            response=interpretation,
            reading_type=reading_type,
            is_premium=use_premium
        )
        
        return web.json_response({
            'success': True,
            'reading': {
                'cards': cards,
                'interpretation': interpretation,
                'reading_type': reading_type,
                'is_premium': use_premium,
            }
        }, headers=cors_headers())
        
    except Exception as e:
        logger.error(f"Reading error: {e}", exc_info=True)
        return web.json_response({
            'success': False,
            'error': str(e)
        }, status=500, headers=cors_headers())


async def handle_history(request: web.Request) -> web.Response:
    """
    GET /api/history
    Возвращает историю раскладов с пагинацией.
    """
    try:
        user_id = get_user_id_from_request(request)
        if not user_id:
            return web.json_response({
                'success': False,
                'error': 'Unauthorized'
            }, status=401, headers=cors_headers())
        
        # Пагинация
        page = int(request.query.get('page', 0))
        limit = int(request.query.get('limit', 10))
        offset = page * limit
        
        # Получаем историю
        history = await db.get_history(user_id, limit=limit, offset=offset)
        total = await db.get_total_history_count(user_id)
        
        # Получаем платежи (с фиксом ORDER BY)
        payments = await db.get_user_payments(user_id, limit=limit, offset=offset)
        
        return web.json_response({
            'success': True,
            'history': history,
            'payments': payments,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
                'total_pages': (total + limit - 1) // limit if total > 0 else 1
            }
        }, headers=cors_headers())
        
    except Exception as e:
        logger.error(f"History error: {e}")
        return web.json_response({
            'success': False,
            'error': str(e)
        }, status=500, headers=cors_headers())


async def handle_payment(request: web.Request) -> web.Response:
    """
    POST /api/payment
    Генерирует ссылку на оплату YooMoney и создаёт pending платёж в БД.
    """
    logger.info("📥 /api/payment endpoint called")
    
    try:
        user_id = get_user_id_from_request(request)
        logger.info(f"💳 Payment request from user_id={user_id}")
        
        if not user_id:
            logger.warning("❌ Payment request without user_id")
            return web.json_response({
                'success': False,
                'error': 'Unauthorized'
            }, status=401, headers=cors_headers())
        
        body = await request.json()
        package_key = body.get('package_key', 'buy_1')
        
        logger.info(f"💳 User {user_id} requested package: {package_key}")
        
        # Получаем тариф
        rates = await db.get_all_rates()
        rate = None
        for r in rates:
            if r['package_key'] == package_key:
                rate = r
                break
        
        if not rate:
            # Fallback на конфиг
            if package_key in PAYMENT_OPTIONS:
                rate = {
                    'package_key': package_key,
                    'requests': PAYMENT_OPTIONS[package_key]['requests'],
                    'price': PAYMENT_OPTIONS[package_key]['price'],
                }
                logger.info(f"💳 Using fallback rate from config: {rate}")
            else:
                logger.error(f"❌ Invalid package_key: {package_key}")
                return web.json_response({
                    'success': False,
                    'error': 'Invalid package'
                }, status=400, headers=cors_headers())
        else:
            logger.info(f"💳 Found rate from DB: {rate}")
        
        # Генерируем ссылку (внутри yoomoney.py также создаётся pending платёж в БД)
        from yoomoney import yoomoney_payment
        
        logger.info(f"💳 Generating payment link for user {user_id}, amount={rate['price']}, requests={rate['requests']}")
        
        payment_url, label = await yoomoney_payment.generate_payment_link(
            user_id=user_id,
            amount=rate['price'],
            requests_count=rate['requests'],
            package_key=package_key
        )
        
        if not payment_url:
            logger.error(f"❌ Failed to generate payment link for user {user_id}")
            return web.json_response({
                'success': False,
                'error': 'Failed to generate payment link'
            }, status=500, headers=cors_headers())
        
        logger.info(f"✅ Payment link created for user {user_id}: label={label[:50]}...")
        
        return web.json_response({
            'success': True,
            'payment': {
                'url': payment_url,
                'label': label,
                'amount': rate['price'],
                'requests': rate['requests'],
                'package_key': package_key,
            }
        }, headers=cors_headers())
        
    except Exception as e:
        logger.error(f"❌ Payment error: {e}", exc_info=True)
        return web.json_response({
            'success': False,
            'error': str(e)
        }, status=500, headers=cors_headers())


async def handle_achievements(request: web.Request) -> web.Response:
    """
    GET /api/achievements
    Возвращает достижения пользователя.
    """
    try:
        user_id = get_user_id_from_request(request)
        if not user_id:
            return web.json_response({
                'success': False,
                'error': 'Unauthorized'
            }, status=401, headers=cors_headers())
        
        achievements = await db.get_user_achievements(user_id)
        level_info = await db.get_user_level_info(user_id)
        
        # Все возможные достижения
        all_achievements = [
            {'name': 'Новичок', 'emoji': '🌱', 'description': 'Сделал первый шаг в мир Таро'},
            {'name': 'Искатель', 'emoji': '🔍', 'description': 'Первый расклад'},
            {'name': 'Ученик', 'emoji': '📚', 'description': '5 раскладов'},
            {'name': 'Практик', 'emoji': '🔮', 'description': '10 раскладов'},
            {'name': 'Адепт', 'emoji': '⭐', 'description': '25 раскладов'},
            {'name': 'Мастер', 'emoji': '🌟', 'description': '50 раскладов'},
            {'name': 'Гуру', 'emoji': '👑', 'description': '100 раскладов'},
            {'name': 'Наставник', 'emoji': '🤝', 'description': 'Пригласил первого друга'},
            {'name': 'Посланник', 'emoji': '📣', 'description': '5 приглашённых друзей'},
            {'name': 'Меценат', 'emoji': '💎', 'description': 'Первая покупка'},
            {'name': 'Покровитель', 'emoji': '💰', 'description': '3 покупки'},
            {'name': 'Постоянный', 'emoji': '🔥', 'description': '3 дня подряд'},
            {'name': 'Ежедневный практик', 'emoji': '🔥🔥', 'description': '7 дней подряд'},
            {'name': 'Непрерывный путь', 'emoji': '🔥🔥🔥', 'description': '30 дней подряд'},
        ]
        
        # Отмечаем полученные
        unlocked_names = {a['achievement_name'] for a in achievements}
        for ach in all_achievements:
            ach['unlocked'] = ach['name'] in unlocked_names
        
        return web.json_response({
            'success': True,
            'achievements': achievements,
            'all_achievements': all_achievements,
            'level': level_info or {'level': 1, 'experience': 0},
        }, headers=cors_headers())
        
    except Exception as e:
        logger.error(f"Achievements error: {e}")
        return web.json_response({
            'success': False,
            'error': str(e)
        }, status=500, headers=cors_headers())


async def handle_rates(request: web.Request) -> web.Response:
    """
    GET /api/rates
    Возвращает доступные тарифы.
    """
    try:
        rates = await db.get_all_rates()
        
        if not rates:
            # Fallback на конфиг
            rates = [
                {
                    'package_key': k,
                    'requests': v['requests'],
                    'price': v['price'],
                    'label': v['label']
                }
                for k, v in PAYMENT_OPTIONS.items()
            ]
        
        return web.json_response({
            'success': True,
            'rates': rates
        }, headers=cors_headers())
        
    except Exception as e:
        logger.error(f"Rates error: {e}")
        return web.json_response({
            'success': False,
            'error': str(e)
        }, status=500, headers=cors_headers())


# ==================== ADMIN ENDPOINTS ====================

async def handle_admin_stats(request: web.Request) -> web.Response:
    """
    GET /api/admin/stats
    Статистика для администратора.
    """
    try:
        user_id = get_user_id_from_request(request)
        if user_id != ADMIN_ID:
            return web.json_response({
                'success': False,
                'error': 'Forbidden'
            }, status=403, headers=cors_headers())
        
        # Получаем статистику
        import sqlite3
        from config import DB_PATH
        
        with sqlite3.connect(str(DB_PATH)) as conn:
            cursor = conn.cursor()
            
            # Общее число пользователей
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
            
            # Активные за 24 часа
            cursor.execute(
                "SELECT COUNT(*) FROM users WHERE last_activity >= datetime('now', '-1 day')"
            )
            active_24h = cursor.fetchone()[0]
            
            # Всего раскладов
            cursor.execute("SELECT COUNT(*) FROM history")
            total_readings = cursor.fetchone()[0]
            
            # Раскладов за 24 часа
            cursor.execute(
                "SELECT COUNT(*) FROM history WHERE timestamp >= datetime('now', '-1 day')"
            )
            readings_24h = cursor.fetchone()[0]
            
            # Платежей всего
            cursor.execute("SELECT COUNT(*), SUM(amount) FROM payments WHERE status = 'confirmed'")
            row = cursor.fetchone()
            total_payments = row[0] or 0
            total_revenue = row[1] or 0
            
            # Ожидающих платежей
            cursor.execute("SELECT COUNT(*) FROM payments WHERE status = 'pending'")
            pending_payments = cursor.fetchone()[0]
        
        return web.json_response({
            'success': True,
            'stats': {
                'total_users': total_users,
                'active_24h': active_24h,
                'total_readings': total_readings,
                'readings_24h': readings_24h,
                'total_payments': total_payments,
                'total_revenue': total_revenue,
                'pending_payments': pending_payments,
            }
        }, headers=cors_headers())
        
    except Exception as e:
        logger.error(f"Admin stats error: {e}")
        return web.json_response({
            'success': False,
            'error': str(e)
        }, status=500, headers=cors_headers())


async def handle_admin_users(request: web.Request) -> web.Response:
    """
    GET /api/admin/users
    Список пользователей для администратора.
    """
    try:
        user_id = get_user_id_from_request(request)
        if user_id != ADMIN_ID:
            return web.json_response({
                'success': False,
                'error': 'Forbidden'
            }, status=403, headers=cors_headers())
        
        page = int(request.query.get('page', 0))
        limit = int(request.query.get('limit', 50))
        offset = page * limit
        
        import sqlite3
        from config import DB_PATH
        
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute(
                """
                SELECT user_id, username, first_name, requests_left, premium_requests, 
                       referrals_count, is_banned, last_activity, created_at
                FROM users 
                ORDER BY created_at DESC 
                LIMIT ? OFFSET ?
                """,
                (limit, offset)
            )
            
            users = [dict(row) for row in cursor.fetchall()]
            
            cursor.execute("SELECT COUNT(*) FROM users")
            total = cursor.fetchone()[0]
        
        return web.json_response({
            'success': True,
            'users': users,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total,
            }
        }, headers=cors_headers())
        
    except Exception as e:
        logger.error(f"Admin users error: {e}")
        return web.json_response({
            'success': False,
            'error': str(e)
        }, status=500, headers=cors_headers())


async def handle_admin_add_requests(request: web.Request) -> web.Response:
    """
    POST /api/admin/add_requests
    Ручное начисление запросов.
    """
    try:
        user_id = get_user_id_from_request(request)
        if user_id != ADMIN_ID:
            return web.json_response({
                'success': False,
                'error': 'Forbidden'
            }, status=403, headers=cors_headers())
        
        body = await request.json()
        target_user_id = body.get('user_id')
        amount = body.get('amount', 1)
        is_premium = body.get('is_premium', True)
        
        if not target_user_id:
            return web.json_response({
                'success': False,
                'error': 'user_id required'
            }, status=400, headers=cors_headers())
        
        success = await db.add_requests_to_user(
            user_id=target_user_id,
            amount=amount,
            is_premium=is_premium
        )
        
        return web.json_response({
            'success': success,
            'message': f'Added {amount} {"premium" if is_premium else "free"} requests to user {target_user_id}'
        }, headers=cors_headers())
        
    except Exception as e:
        logger.error(f"Admin add requests error: {e}")
        return web.json_response({
            'success': False,
            'error': str(e)
        }, status=500, headers=cors_headers())


# ==================== HEALTH CHECK ====================

async def handle_health(request: web.Request) -> web.Response:
    """GET /api/health - проверка доступности API."""
    return web.json_response({
        'success': True,
        'status': 'ok',
        'message': 'API is running'
    }, headers=cors_headers())


# ==================== API SETUP ====================

def setup_api_routes(app: web.Application) -> None:
    """Настраивает API роуты."""
    
    # Health check
    app.router.add_get('/api/health', handle_health)
    
    # Public endpoints
    app.router.add_post('/api/auth', handle_auth)
    app.router.add_get('/api/user', handle_get_user)
    app.router.add_post('/api/reading', handle_reading)
    app.router.add_get('/api/history', handle_history)
    app.router.add_post('/api/payment', handle_payment)
    app.router.add_get('/api/achievements', handle_achievements)
    app.router.add_get('/api/rates', handle_rates)
    
    # Admin endpoints
    app.router.add_get('/api/admin/stats', handle_admin_stats)
    app.router.add_get('/api/admin/users', handle_admin_users)
    app.router.add_post('/api/admin/add_requests', handle_admin_add_requests)
    
    # OPTIONS для CORS preflight
    app.router.add_route('OPTIONS', '/api/{path:.*}', lambda r: web.Response(status=200, headers=cors_headers()))


def create_api_app() -> web.Application:
    """Создаёт aiohttp приложение с API."""
    app = web.Application(middlewares=[cors_middleware])
    setup_api_routes(app)
    return app
