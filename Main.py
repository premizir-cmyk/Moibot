import os
import re
import json
import time
import pytz
import zipfile
import telebot
import threading
import urllib.parse
from datetime import datetime, time as dt_time, timedelta
from telebot import types

# --- ОСНОВНЫЕ НАСТРОЙКИ ПОД ТВОЙ КАНАЛ И БОТА ---
TOKEN = '8282256956:AAH-LPJFnh8HYnMHuP8-R1uQGTQ2P-_-pYk'
CHANNEL_ID = '@otzovzaden'
BOT_USERNAME = '@Dengaotziv_bot'
MY_USERNAME = '@premizir'  # Твой юзернейм для связи

OWNER_ID = [7605961809]  # Твой ID владельца

bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=16)

# --- НАСТРОЙКА ХРАНЕНИЯ ФАЙЛОВ НА BOTHOST ---
DATA_DIR = '/app/data' if os.path.exists('/app/data') else '.'
DB_FILE = os.path.join(DATA_DIR, 'users.json')
COOLDOWN_FILE = os.path.join(DATA_DIR, 'cooldowns.json')
PLATFORM_HISTORY_FILE = os.path.join(DATA_DIR, 'platform_history.json')  # История платформ для раздельного кулдауна
NOTIFIED_FILE = os.path.join(DATA_DIR, 'notified.json')
HISTORY_FILE = os.path.join(DATA_DIR, 'history.json')
POSTS_FILE = os.path.join(DATA_DIR, 'active_posts.json')
SCHEDULED_POSTS_FILE = os.path.join(DATA_DIR, 'scheduled_posts.json')
CD_NOTIFIED_FILE = os.path.join(DATA_DIR, 'cd_notified.json')
CD_PRENOTIFIED_FILE = os.path.join(DATA_DIR, 'cd_prenotified.json')
BAN_FILE = os.path.join(DATA_DIR, 'blacklist.json')
SLOT_COUNTER_FILE = os.path.join(DATA_DIR, 'slot_counter.json')
SETTINGS_FILE = os.path.join(DATA_DIR, 'settings.json')
BACKUP_LOG_FILE = os.path.join(DATA_DIR, 'backup_log.json')

COOLDOWN_TIME = 9000    # 2.5 часа общий кулдаун между постами одного юзера (в секундах)
AUTO_CLOSE_TIME = 7200  # 2 часа до автозакрытия поста (в секундах)
MIN_OTHER_POSTS_FOR_SAME_PLATFORM = 3  # Сколько чужих/других постов должно пройти перед повтором платформы

# Расширенный список запрещенных скам-слов
FORBIDDEN_WORDS = ['казино', '1win', 'крипта', 'трейдинг', 'пирамида', 'darknet', 'нарко', 'взлом', 'пробив', 'софт']

# Ключевые слова, указывающие на РЕАЛЬНОЕ задание / слот
TASK_KEYWORDS = [
    'отзыв', 'оценка', 'звезд', 'звёзд', 'карты', 'яндекс', 'гугл', 'авито', '2гис', 'профиль',
    'пушкинск', 'пушка', 'билет', 'мероприятие', 'баланс',
    'wb', 'wildberries', 'вайлдберриз', 'озон', 'ozon', 'мегамаркет', 'выкуп', 'избранное', 'товар',
    'написать', 'оформить', 'скачать', 'подписка', 'регистрация', 'рег', 'пройти', 'прогрев',
    'аккаунт', 'акк', 'номер', 'смс', 'приложение', 'промокод',
    'соцсети', 'соцсетей', 'контент', 'reels', 'посты', 'сторис', 'работа', 'вакансия'
]

file_lock = threading.Lock()

# Хранилища временных состояний
user_creation_data = {}  
user_states = {}         

RULES_TEXT = """⚠️ **ПРАВИЛА ПУБЛИКАЦИИ:**

1. **Используйте пошаговый конструктор!** Запрещено указывать юзернеймы и ссылки в тексте.
2. **Запрещен скам и бессмысленные задания!** 
3. **Кулдаун:** Между постами одного автора 2.5 часа. Одинаковые платформы чередуются через каждые 3 других поста.
4. **Обязательна подписка** на наш канал.

🚨 *За нарушение правил доступ аннулируется без возврата средств!*"""

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ БАЗ ДАННЫХ И НАСТРОЕК ---

def load_data(filename):
    with file_lock:
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Ошибка чтения {filename}: {e}")
                return [] if filename.endswith(('history.json', 'blacklist.json', 'platform_history.json')) else {}
        return [] if filename.endswith(('history.json', 'blacklist.json', 'platform_history.json')) else {}

def save_data(filename, data):
    with file_lock:
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка сохранения {filename}: {e}")

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Ошибка чтения настроек: {e}")
    return {"night_photo": None, "morning_photo": None}

def save_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Ошибка сохранения настроек: {e}")

def get_next_slot_id():
    counter_data = load_data(SLOT_COUNTER_FILE)
    if not isinstance(counter_data, dict):
        counter_data = {"count": 1000}
    current = counter_data.get("count", 1000) + 1
    counter_data["count"] = current
    save_data(SLOT_COUNTER_FILE, counter_data)
    return current

def is_banned(user_id):
    blacklist = load_data(BAN_FILE)
    return str(user_id) in blacklist or user_id in blacklist

def is_owner(user_id):
    return user_id in OWNER_ID

def check_channel_subscription(user_id):
    if is_owner(user_id):
        return True
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception:
        return True

def is_user_active(user_id):
    if is_owner(user_id):
        return True
    if is_banned(user_id):
        return False
    users = load_data(DB_FILE)
    str_id = str(user_id)
    if str_id in users:
        data = users[str_id]
        if isinstance(data, dict):
            exp_time = data.get("expire", 0)
            posts_left = data.get("posts", 0)
            if (exp_time > 0 and time.time() < exp_time) or posts_left > 0:
                return True
        elif isinstance(data, (int, float)):
            if time.time() < data:
                return True
            else:
                del users[str_id]
                save_data(DB_FILE, users)
    return False

def consume_post_credit(user_id):
    if is_owner(user_id):
        return
    users = load_data(DB_FILE)
    str_id = str(user_id)
    if str_id in users and isinstance(users[str_id], dict):
        if users[str_id].get("posts", 0) > 0:
            users[str_id]["posts"] -= 1
            save_data(DB_FILE, users)

def get_cooldown_left(user_id):
    if is_owner(user_id):
        return 0
    cooldowns = load_data(COOLDOWN_FILE)
    str_id = str(user_id)
    if str_id in cooldowns:
        last_post_time = cooldowns[str_id]
        elapsed = time.time() - last_post_time
        if elapsed < COOLDOWN_TIME:
            return int(COOLDOWN_TIME - elapsed)
    return 0

def set_cooldown(user_id):
    if is_owner(user_id):
        return
    cooldowns = load_data(COOLDOWN_FILE)
    cooldowns[str(user_id)] = time.time()
    save_data(COOLDOWN_FILE, cooldowns)
    
    cd_notified = load_data(CD_NOTIFIED_FILE)
    cd_prenotified = load_data(CD_PRENOTIFIED_FILE)
    if str(user_id) in cd_notified:
        del cd_notified[str(user_id)]
        save_data(CD_NOTIFIED_FILE, cd_notified)
    if str(user_id) in cd_prenotified:
        del cd_prenotified[str(user_id)]
        save_data(CD_PRENOTIFIED_FILE, cd_prenotified)

def reset_cooldown(user_id):
    cooldowns = load_data(COOLDOWN_FILE)
    str_id = str(user_id)
    if str_id in cooldowns:
        del cooldowns[str_id]
        save_data(COOLDOWN_FILE, cooldowns)

def normalize_platform_name(platform_text):
    text = platform_text.lower().strip()
    if any(w in text for w in ['яндекс', 'yandex', 'карты', 'навигатор']):
        return 'Яндекс Карты / Сервисы'
    if any(w in text for w in ['авито', 'avito']):
        return 'Авито'
    if any(w in text for w in ['wb', 'wildberries', 'вайлдберриз']):
        return 'Wildberries'
    if any(w in text for w in ['озон', 'ozon']):
        return 'Ozon'
    if any(w in text for w in ['гугл', 'google', 'maps']):
        return 'Google Карты'
    if any(w in text for w in ['2гис', '2gis']):
        return '2ГИС'
    return text.capitalize()

def check_platform_cooldown(platform_name):
    norm_name = normalize_platform_name(platform_name)
    history = load_data(PLATFORM_HISTORY_FILE)
    if not isinstance(history, list):
        history = []
    
    count_since_last = 0
    found = False
    for item in reversed(history):
        if item.get('platform') == norm_name:
            found = True
            break
        count_since_last += 1
        
    if not found:
        return True, 0  
        
    if count_since_last >= MIN_OTHER_POSTS_FOR_SAME_PLATFORM:
        return True, 0
    else:
        needed = MIN_OTHER_POSTS_FOR_SAME_PLATFORM - count_since_last
        return False, needed

def get_next_available_slot_for_platform(platform_name):
    """Рассчитывает ориентировочное время, когда платформа будет доступна после 3 постов."""
    norm_name = normalize_platform_name(platform_name)
    history = load_data(PLATFORM_HISTORY_FILE)
    if not isinstance(history, list):
        history = []
    
    count_since_last = 0
    for item in reversed(history):
        if item.get('platform') == norm_name:
            break
        count_since_last += 1
        
    needed_posts = max(0, MIN_OTHER_POSTS_FOR_SAME_PLATFORM - count_since_last)
    
    # Шаг слота 20 минут (1200 секунд), умножаем на оставшиеся посты + 1 слот
    delay_seconds = (needed_posts + 1) * 1200 
    available_timestamp = time.time() + delay_seconds
    
    tz = pytz.timezone('Europe/Moscow')
    available_dt = datetime.fromtimestamp(available_timestamp, tz)
    return available_dt.strftime('%d.%m в %H:%M МСК'), needed_posts

def register_platform_publication(platform_name):
    norm_name = normalize_platform_name(platform_name)
    history = load_data(PLATFORM_HISTORY_FILE)
    if not isinstance(history, list):
        history = []
    history.append({"platform": norm_name, "timestamp": time.time()})
    if len(history) > 100:
        history = history[-100:]
    save_data(PLATFORM_HISTORY_FILE, history)

def save_to_history(user_id, username, text):
    history = load_data(HISTORY_FILE)
    if not isinstance(history, list):
        history = []
    
    post_entry = {
        "timestamp": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "user_id": user_id,
        "username": username or "Без username",
        "text": text[:300]
    }
    history.append(post_entry)
    if len(history) > 50:
        history = history[-50:]
    save_data(HISTORY_FILE, history)

def format_time(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours} ч. {minutes} мин." if hours > 0 else f"{minutes} мин."

def close_post_in_channel(message_id):
    CLOSED_CARD = (
        "🔒 **[СЛОТ ЗАКРЫТ]**\n\n"
        "━━━━━⬍━━━━━\n"
        "⛔ *Набор на этот слот завершён.*\n"
        "🔔 Включите уведомления в канале, чтобы не пропустить новые предложения!\n\n"
        f"🤖 *Хотите такого же бота в свой канал? Пишите разработчику:* {MY_USERNAME}"
    )

    try:
        bot.edit_message_text(text=CLOSED_CARD, chat_id=CHANNEL_ID, message_id=message_id, parse_mode="Markdown", reply_markup=None)
        return True
    except Exception:
        try:
            bot.delete_message(chat_id=CHANNEL_ID, message_id=message_id)
            bot.send_message(chat_id=CHANNEL_ID, text=CLOSED_CARD, parse_mode="Markdown")
            return True
        except:
            return False

# --- ФУНКЦИИ ГЕНЕРАЦИИ СЛОТОВ ---
def get_available_slots_keyboard(user_id):
    tz = pytz.timezone('Europe/Moscow')
    now = datetime.now(tz)
    
    scheduled_data = load_data(SCHEDULED_POSTS_FILE)
    if not isinstance(scheduled_data, dict):
        scheduled_data = {}

    cd_left = get_cooldown_left(user_id)
    earliest_available_time = now.timestamp() + cd_left

    markup = types.InlineKeyboardMarkup(row_width=2)
    
    if 0 <= now.hour < 10:
        start_dt = now.replace(hour=10, minute=0, second=0, microsecond=0)
    else:
        minute = now.minute
        rem = minute % 20
        add_min = 20 - rem if rem != 0 else 20
        start_dt = now + timedelta(minutes=add_min)
        start_dt = start_dt.replace(second=0, microsecond=0)

    max_end_dt = start_dt + timedelta(hours=1)

    slot_dt = start_dt
    slots_count = 0
    while slot_dt <= max_end_dt and slots_count < 4:
        if 0 <= slot_dt.hour < 10:
            slot_dt += timedelta(minutes=20)
            continue

        slot_str = slot_dt.strftime("%H:%M")
        timestamp_key = str(int(slot_dt.timestamp()))
        slot_timestamp = slot_dt.timestamp()
        
        if timestamp_key in scheduled_data:
            slot_info = scheduled_data[timestamp_key]
            platform_name = slot_info.get("platform", "")
            if platform_name:
                btn_text = f"❌ {slot_str} ({platform_name})"
            else:
                btn_text = f"❌ {slot_str} (Занято)"
            callback_data = "slot_busy"
        elif slot_timestamp < earliest_available_time:
            btn_text = f"⏳ {slot_str} (КД)"
            callback_data = "slot_cooldown_active"
        else:
            btn_text = f"🟢 {slot_str} МСК"
            callback_data = f"book_slot_{timestamp_key}"
            slots_count += 1
            
        markup.add(types.InlineKeyboardButton(text=btn_text, callback_data=callback_data))
        slot_dt += timedelta(minutes=20)

    markup.add(types.InlineKeyboardButton(text="🔄 Обновить слоты", callback_data="refresh_slots"))
    markup.add(types.InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_publish"))
    return markup

# --- ФУНКЦИИ БЭКАПА ---

def can_send_backup():
    with file_lock:
        if not os.path.exists(BACKUP_LOG_FILE):
            return True
        try:
            with open(BACKUP_LOG_FILE, 'r') as f:
                last_date_str = json.load(f).get('last_backup_date')
                if not last_date_str: return True
                last_date = datetime.strptime(last_date_str, '%Y-%m-%d').date()
                today = datetime.now().date()
                return today > last_date
        except:
            return True

def log_backup_sent():
    with file_lock:
        today_str = datetime.now().strftime('%Y-%m-%d')
        with open(BACKUP_LOG_FILE, 'w') as f:
            json.dump({'last_backup_date': today_str}, f)

def send_backup_to_owner():
    try:
        backup_filename = os.path.join(DATA_DIR, f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
        with zipfile.ZipFile(backup_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(DATA_DIR):
                for file in files:
                    if file.endswith('.json'):
                        zipf.write(os.path.join(root, file), arcname=file)
        
        if OWNER_ID:
            primary_owner = OWNER_ID[0]
            caption = f"📦 **АВТО-БЭКАП БАЗЫ ДАННЫХ**\n📅 `{datetime.now().strftime('%d.%m.%Y %H:%M')}`"
            with open(backup_filename, 'rb') as doc:
                bot.send_document(primary_owner, doc, caption=caption, parse_mode="Markdown")
        
        if os.path.exists(backup_filename):
            os.remove(backup_filename)
    except Exception as e:
        print(f"Ошибка проведения бэкапа: {e}")

# --- ФОНОВЫЕ ПОТОКИ ---

def scheduled_posts_checker():
    while True:
        try:
            scheduled_data = load_data(SCHEDULED_POSTS_FILE)
            if isinstance(scheduled_data, dict) and scheduled_data:
                now_ts = time.time()
                for ts_str, p_info in list(scheduled_data.items()):
                    if now_ts >= float(ts_str):
                        user_id = p_info['user_id']
                        username = p_info['username']
                        final_text = p_info['final_text']
                        slot_num = p_info['slot_num']
                        platform = p_info['platform']
                        payment = p_info['payment']

                        try:
                            auto_msg = f"Здравствуйте! Я хочу у вас взять {platform} за {payment}руб! Из канала {CHANNEL_ID}"
                            encoded_text = urllib.parse.quote(auto_msg)
                            direct_url = f"https://t.me/{username}?text={encoded_text}" if username else f"tg://user?id={user_id}"
                            clean_bot_username = BOT_USERNAME.replace('@', '')

                            published_msg = bot.send_message(CHANNEL_ID, final_text)
                            
                            markup = types.InlineKeyboardMarkup(row_width=1)
                            markup.add(
                                types.InlineKeyboardButton(text="Перейти к выполнению 💬", url=direct_url),
                                types.InlineKeyboardButton(text="🚫 У меня спам-блок", callback_data=f"spamblock_{published_msg.message_id}"),
                                types.InlineKeyboardButton(text="🚨 Пожаловаться (на любого админа)", url=f"https://t.me/{clean_bot_username}?start=report_{slot_num}")
                            )
                            bot.edit_message_reply_markup(chat_id=CHANNEL_ID, message_id=published_msg.message_id, reply_markup=markup)

                            consume_post_credit(user_id)
                            set_cooldown(user_id)
                            register_platform_publication(platform)
                            save_to_history(user_id, username, final_text)
                            
                            user_creation_data[user_id] = {
                                'platform': platform,
                                'payment': payment,
                                'desc': final_text,
                                'final_text': final_text
                            }

                            confirm_markup = types.InlineKeyboardMarkup(row_width=2)
                            confirm_markup.add(
                                types.InlineKeyboardButton(text="🔄 Повторить пост", callback_data="repeat_last_post"),
                                types.InlineKeyboardButton(text="📝 Новый пост", callback_data="start_create_post")
                            )
                            confirm_markup.add(types.InlineKeyboardButton(text="📱 Главное меню", callback_data="main_menu"))

                            confirm_msg = bot.send_message(
                                user_id,
                                f"🚀 **Ваш забронированный слот #{slot_num} успешно опубликован в канале!**\n\n"
                                "📌 **Как закрыть пост:** Ответьте `/close` на уведомление.",
                                parse_mode="Markdown",
                                reply_markup=confirm_markup
                            )

                            posts_data = load_data(POSTS_FILE)
                            posts_data[str(published_msg.message_id)] = {
                                "user_id": user_id,
                                "created_at": time.time(),
                                "confirm_msg_id": confirm_msg.message_id,
                                "platform": platform,
                                "payment": payment,
                                "slot_num": f"СЛОТ-{slot_num}"
                            }
                            save_data(POSTS_FILE, posts_data)

                        except Exception as e:
                            print(f"Ошибка автоотправки забронированного поста: {e}")

                        del scheduled_data[ts_str]
                        save_data(SCHEDULED_POSTS_FILE, scheduled_data)
        except Exception as e:
            print(f"Ошибка потока расписания: {e}")
        time.sleep(10)

def auto_close_checker():
    while True:
        try:
            posts_data = load_data(POSTS_FILE)
            now = time.time()
            changed = False
            for p_id, p_info in list(posts_data.items()):
                if now - p_info.get("created_at", 0) >= AUTO_CLOSE_TIME:
                    close_post_in_channel(int(p_id))
                    del posts_data[p_id]
                    changed = True
            if changed:
                save_data(POSTS_FILE, posts_data)
        except Exception as e:
            print(f"Ошибка автозакрытия: {e}")
        time.sleep(15)

def check_expiring_subscriptions_and_cooldowns():
    while True:
        try:
            users = load_data(DB_FILE)
            notified = load_data(NOTIFIED_FILE)
            cooldowns = load_data(COOLDOWN_FILE)
            cd_notified = load_data(CD_NOTIFIED_FILE)
            cd_prenotified = load_data(CD_PRENOTIFIED_FILE)
            now = time.time()
            
            for u_id, u_info in list(users.items()):
                exp_time = u_info.get("expire", 0) if isinstance(u_info, dict) else u_info
                time_left = exp_time - now
                if 0 < time_left <= 86400 and u_id not in notified:
                    try:
                        bot.send_message(int(u_id), f"⚠️ **Внимание!** Ваша подписка закончится через 24 часа.\nДля продления пишите {MY_USERNAME}", parse_mode="Markdown")
                    except:
                        pass
                    notified[u_id] = True
                    save_data(NOTIFIED_FILE, notified)

            for u_id, last_time in list(cooldowns.items()):
                elapsed = now - last_time
                time_left = COOLDOWN_TIME - elapsed
                
                if 0 < time_left <= 300 and u_id not in cd_prenotified:
                    try:
                        bot.send_message(int(u_id), "⏳ **До окончания кулдауна осталось 5 минут!**\nМожете готовить новый слот.", parse_mode="Markdown")
                    except:
                        pass
                    cd_prenotified[u_id] = True
                    save_data(CD_PRENOTIFIED_FILE, cd_prenotified)

                if elapsed >= COOLDOWN_TIME and u_id not in cd_notified:
                    try:
                        bot.send_message(int(u_id), "⚡ **Твой кулдаун окончен!**\nВы можете опубликовать новый слот прямо сейчас.", parse_mode="Markdown")
                    except:
                        pass
                    cd_notified[u_id] = True
                    save_data(CD_NOTIFIED_FILE, cd_notified)

        except Exception as e:
            print(f"Ошибка фона: {e}")
        time.sleep(30)

def backup_scheduler():
    time.sleep(10)
    while True:
        try:
            if can_send_backup():
                send_backup_to_owner()
                log_backup_sent()
        except Exception as e:
            print(f"Ошибка автобэкапа: {e}")
        time.sleep(3600)

def quiet_hours_channel_announcer():
    tz = pytz.timezone('Europe/Moscow')
    night_posted_date = None
    morning_posted_date = None

    while True:
        try:
            now = datetime.now(tz)
            today_str = now.strftime('%Y-%m-%d')
            settings = load_settings()

            if now.hour == 0 and now.minute < 2 and night_posted_date != today_str:
                text_night = (
                    "🌙 **Канал уходит на ночной перерыв!**\n\n"
                    "😴 Все слоты и задания отправляются отдыхать до 10:00 утра, чтобы никому не мешать спать.\n\n"
                    "🔔 *Включайте уведомления — ровно в 10:00 МСК канал проснется, и вас будут ждать новые свежие задания!*\n\n"
                    "Всем хорошей ночи и отличного отдыха! 💤"
                )
                photo = settings.get("night_photo")
                if photo:
                    bot.send_photo(CHANNEL_ID, photo, caption=text_night, parse_mode="Markdown")
                else:
                    bot.send_message(CHANNEL_ID, text_night, parse_mode="Markdown")
                night_posted_date = today_str

            elif now.hour == 10 and now.minute < 2 and morning_posted_date != today_str:
                text_morning = (
                    "☀️ **Доброе утро! Канал проснулся!**\n\n"
                    "🚀 Тихий час окончен — выкладка заданий снова активна!\n\n"
                    "Заказчики уже могут отправлять новые слоты через бота. Держите уведомления включенными, чтобы успевать забирать самые выгодные варианты! 🔥\n\n"
                    f"👉 **Выложить слот:** {BOT_USERNAME}"
                )
                photo = settings.get("morning_photo")
                if photo:
                    bot.send_photo(CHANNEL_ID, photo, caption=text_morning, parse_mode="Markdown")
                else:
                    bot.send_message(CHANNEL_ID, text_morning, parse_mode="Markdown")
                morning_posted_date = today_str

        except Exception as e:
            print(f"Ошибка тихого часа: {e}")
        time.sleep(30)

# --- КЛАВИАТУРЫ И МЕНЮ ---

def get_persistent_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("📱 Главное меню"))
    return markup

def get_main_menu_keyboard(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(text="📝 Выставить пост", callback_data="start_create_post"),
        types.InlineKeyboardButton(text="📅 Свободное время / Бронь", callback_data="open_slots_menu"),
        types.InlineKeyboardButton(text="📖 Правила", callback_data="show_rules"),
        types.InlineKeyboardButton(text="⏳ Мой профиль / КД", callback_data="my_profile"),
        types.InlineKeyboardButton(text="📅 Мои брони", callback_data="my_scheduled_posts"),
        types.InlineKeyboardButton(text="🚨 Пожаловаться на скам", callback_data="report_scam")
    )
    markup.add(types.InlineKeyboardButton(text="🤖 Хочу такого же бота себе", url=f"https://t.me/{MY_USERNAME.replace('@', '')}"))
    
    if is_owner(user_id):
        markup.add(types.InlineKeyboardButton(text="🛠 Админ-панель", callback_data="open_admin_help"))
    return markup

def get_back_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="main_menu"))
    return markup

def get_admin_help_text():
    return (
        "🛠 **ПАНЕЛЬ УПРАВЛЕНИЯ ВЛАДЕЛЬЦА:**\n\n"
        "🟢 `/add ID ДНИ [ПОСТЫ]` — Выдать доступ (Пример: `/add 12345 30` или `/add 12345 0 5`)\n"
        "🔴 `/del ID` — Забрать доступ у пользователя\n"
        "⛔ `/ban ID` — Забанить пользователя\n"
        "🟢 `/unban ID` — Разбанить пользователя\n"
        "👤 `/user ID` — Карточка пользователя\n"
        "📋 `/list` — Список активных подписок\n"
        "📊 `/stats` — Статистика бота\n"
        "📢 `/broadcast ТЕКСТ` — Рассылка всем\n"
        "⚡ `/uncd ID` — Сбросить кулдаун юзеру\n"
        "📜 `/history` — История публикаций\n"
        "📦 `/backup` — Получить бэкап баз в .zip\n\n"
        "🖼 **Настройка картинок (Тихий час):**\n"
        "Пришли картинку в ЛС с подписью `/set_night` или `/set_morning`"
    )

REPORT_TEXT = (
    "🚨 **Оформление жалобы на скам:**\n\n"
    "Отправь в ответ **ОДНИМ СООБЩЕНИЕМ**:\n"
    "1. Юзернейм/ID заказчика или номер слота.\n"
    "2. Скриншот вашей работы.\n"
    "3. Скриншот переписки с отказом оплаты.\n\n"
    "👇 **Ждём сообщение ниже:** (для отмены /cancel)"
)

# --- АДМИН-КОМАНДЫ ---

@bot.message_handler(commands=['adminhelp'])
def admin_help_cmd(message):
    if not is_owner(message.from_user.id): return
    bot.reply_to(message, get_admin_help_text(), parse_mode="Markdown")

@bot.message_handler(commands=['backup'])
def manual_backup_cmd(message):
    if not is_owner(message.from_user.id): return
    bot.reply_to(message, "⏳ Создаю и отправляю архив базы данных...")
    send_backup_to_owner()

@bot.message_handler(commands=['ban'])
def ban_user_cmd(message):
    if not is_owner(message.from_user.id): return
    try:
        target_id = str(message.text.split()[1])
        blacklist = load_data(BAN_FILE)
        if target_id not in blacklist:
            blacklist.append(target_id)
            save_data(BAN_FILE, blacklist)
        users = load_data(DB_FILE)
        if target_id in users:
            del users[target_id]
            save_data(DB_FILE, users)
        bot.reply_to(message, f"⛔ Пользователь `{target_id}` забанен!", parse_mode="Markdown")
    except:
        bot.reply_to(message, "Формат: `/ban ID`", parse_mode="Markdown")

@bot.message_handler(commands=['unban'])
def unban_user_cmd(message):
    if not is_owner(message.from_user.id): return
    try:
        target_id = str(message.text.split()[1])
        blacklist = load_data(BAN_FILE)
        if target_id in blacklist:
            blacklist.remove(target_id)
            save_data(BAN_FILE, blacklist)
            bot.reply_to(message, f"✅ Пользователь `{target_id}` разбанен!", parse_mode="Markdown")
    except:
        bot.reply_to(message, "Формат: `/unban ID`", parse_mode="Markdown")

@bot.message_handler(commands=['add'])
def add_user(message):
    if not is_owner(message.from_user.id): return
    try:
        args = message.text.split()
        target_id, days = str(args[1]), int(args[2])
        posts = int(args[3]) if len(args) > 3 else 0

        users = load_data(DB_FILE)
        exp_time = time.time() + (days * 86400) if days > 0 else 0
        users[target_id] = {"expire": exp_time, "posts": posts}
        save_data(DB_FILE, users)

        msg_text = f"✅ Доступ для ID `{target_id}` успешно обновлен!\n"
        if days > 0: msg_text += f"• Подписка: **{days} дн.**\n"
        if posts > 0: msg_text += f"• Разовые посты: **{posts} шт.**"

        bot.reply_to(message, msg_text, parse_mode="Markdown")
        try:
            bot.send_message(int(target_id), f"🎉 **Вам обновлен доступ к боту!**\n\n{msg_text}\n\nНажмите /start для начала.", reply_markup=get_persistent_keyboard())
        except: pass
    except Exception:
        bot.reply_to(message, "❌ Формат: `/add ID ДНИ [ПОСТЫ]`", parse_mode="Markdown")

@bot.message_handler(commands=['del'])
def del_user(message):
    if not is_owner(message.from_user.id): return
    try:
        target_id = str(message.text.split()[1])
        users = load_data(DB_FILE)
        if target_id in users:
            del users[target_id]
            save_data(DB_FILE, users)
            bot.reply_to(message, f"⛔ Доступ для ID `{target_id}` аннулирован.", parse_mode="Markdown")
    except:
        bot.reply_to(message, "Формат: `/del ID`", parse_mode="Markdown")

@bot.message_handler(commands=['user'])
def user_info_cmd(message):
    if not is_owner(message.from_user.id): return
    try:
        arg = message.text.split()[1].replace('@', '')
        users = load_data(DB_FILE)
        target_id = arg if arg.isdigit() and arg in users else None

        if not target_id:
            history = load_data(HISTORY_FILE)
            for h in reversed(history):
                if h.get('username', '').lower() == arg.lower():
                    target_id = str(h['user_id'])
                    break

        if not target_id or target_id not in users:
            bot.reply_to(message, "❌ Пользователь не найден в активной базе.")
            return

        u_info = users[target_id]
        now = time.time()
        exp_time = u_info.get("expire", 0) if isinstance(u_info, dict) else u_info
        posts_left = u_info.get("posts", 0) if isinstance(u_info, dict) else 0
        days_left = round((exp_time - now) / 86400, 1) if exp_time > now else 0
        cd_left = get_cooldown_left(target_id)
        
        text = (
            f"👤 **Карточка юзера `ID {target_id}`:**\n\n"
            f"• Подписка по дням: **{days_left} дн.**\n"
            f"• Оставшиеся посты: **{posts_left} шт.**\n"
            f"• Кулдаун: **{format_time(cd_left) if cd_left > 0 else 'Нет'}**"
        )
        bot.reply_to(message, text, parse_mode="Markdown")
    except:
        bot.reply_to(message, "❌ Формат: `/user ID` или `/user @username`", parse_mode="Markdown")

@bot.message_handler(commands=['stats'])
def stats_cmd(message):
    if not is_owner(message.from_user.id): return
    users = load_data(DB_FILE)
    history = load_data(HISTORY_FILE)
    active_posts = load_data(POSTS_FILE)
    
    active_sub_count = sum(1 for u in users.values() if (u.get("expire", 0) > time.time()) or u.get("posts", 0) > 0)
    text = (
        "📊 **СТАТИСТИКА БОТА:**\n\n"
        f"👥 Всего пользователей с доступом: **{len(users)}**\n"
        f"🟢 Активных подписок/постов: **{active_sub_count}**\n"
        f"📌 Постов в истории: **{len(history)}**\n"
        f"⏳ Активных слотов сейчас: **{len(active_posts)}**"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['broadcast'])
def broadcast_cmd(message):
    if not is_owner(message.from_user.id): return
    text_to_send = message.text.replace('/broadcast', '').strip()
    if not text_to_send:
        bot.reply_to(message, "❌ Напишите текст: `/broadcast Текст...`", parse_mode="Markdown")
        return

    users = load_data(DB_FILE)
    success, failed = 0, 0
    bot.reply_to(message, f"📢 Запускаю рассылку на {len(users)} пользователей...")
    for u_id in list(users.keys()):
        try:
            bot.send_message(int(u_id), f"📢 **Объявление:**\n\n{text_to_send}", parse_mode="Markdown")
            success += 1
            time.sleep(0.05)
        except: failed += 1
    bot.send_message(message.chat.id, f"✅ **Рассылка завершена!**\nУспешно: {success} | Ошибок: {failed}", parse_mode="Markdown")

@bot.message_handler(commands=['list'])
def list_users(message):
    if not is_owner(message.from_user.id): return
    users = load_data(DB_FILE)
    if not users:
        bot.reply_to(message, "Список пуст.")
        return
    
    text = "📋 **Активные подписки и посты:**\n\n"
    now = time.time()
    for u_id, u_info in list(users.items()):
        exp_time = u_info.get("expire", 0) if isinstance(u_info, dict) else u_info
        posts_left = u_info.get("posts", 0) if isinstance(u_info, dict) else 0
        left_days = round((exp_time - now) / 86400, 1)
        if left_days > 0 or posts_left > 0:
            info_str = []
            if left_days > 0: info_str.append(f"{left_days} дн.")
            if posts_left > 0: info_str.append(f"{posts_left} постов")
            text += f"• ID `{u_id}` — осталось: **{', '.join(info_str)}**\n"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['uncd', 'uncooldown'])
def reset_cooldown_command(message):
    if not is_owner(message.from_user.id): return
    try:
        target_id = str(message.text.split()[1])
        reset_cooldown(target_id)
        bot.reply_to(message, f"⚡ Кулдаун для ID `{target_id}` сброшен!", parse_mode="Markdown")
    except:
        bot.reply_to(message, "Формат: `/uncd ID`", parse_mode="Markdown")

@bot.message_handler(commands=['history'])
def show_history(message):
    if not is_owner(message.from_user.id): return
    history = load_data(HISTORY_FILE)
    if not history:
        bot.reply_to(message, "История постов пуста.")
        return
    text = "📜 **История последних публикаций:**\n\n"
    for item in history[-10:]:
        user_str = f"@{item['username']}" if item['username'] != "Без username" else f"ID {item['user_id']}"
        text += f"🕒 [{item['timestamp']}] {user_str}\n💬 {item['text'][:80]}...\n---\n"
    bot.reply_to(message, text)

@bot.message_handler(commands=['close'])
def close_user_post(message):
    user_id = message.from_user.id
    posts_data = load_data(POSTS_FILE)
    target_post_id = None
    
    if message.reply_to_message:
        for p_id, p_info in posts_data.items():
            if p_info.get("confirm_msg_id") == message.reply_to_message.message_id:
                target_post_id = p_id
                break
    if not target_post_id:
        user_posts = [p_id for p_id, info in posts_data.items() if info.get("user_id") == user_id]
        if user_posts: target_post_id = user_posts[-1]

    if target_post_id and target_post_id in posts_data:
        post_info = posts_data[target_post_id]
        if post_info["user_id"] != user_id and not is_owner(user_id):
            bot.reply_to(message, "⛔ Вы не можете закрыть чужой пост.")
            return

        time_passed = time.time() - post_info.get("created_at", time.time())
        close_post_in_channel(int(target_post_id))
        del posts_data[target_post_id]
        save_data(POSTS_FILE, posts_data)

        if time_passed <= 60:
            reset_cooldown(user_id)
            bot.reply_to(message, "✅ **Пост закрыт!** ⚡ Кулдаун сброшен!")
        else:
            bot.reply_to(message, "✅ **Пост закрыт!**")
    else:
        bot.reply_to(message, "❌ Активный пост не найден.")

@bot.message_handler(content_types=['document'])
def handle_restore_backup(message):
    if not is_owner(message.from_user.id): return
    if not message.document.file_name.endswith('.zip'):
        bot.reply_to(message, "❌ Пришлите .zip архив базы данных.")
        return

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        zip_path = os.path.join(DATA_DIR, "restore.zip")
        
        with open(zip_path, 'wb') as f:
            f.write(downloaded)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(DATA_DIR)
        os.remove(zip_path)
        
        bot.reply_to(message, "✅ **База данных успешно восстановлена из архива!**", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка восстановления: {e}")

@bot.message_handler(content_types=['photo'], func=lambda m: m.caption in ['/set_night', '/set_morning'])
def set_scheduled_photos(message):
    if not is_owner(message.from_user.id): return
    settings = load_settings()
    photo_id = message.photo[-1].file_id

    if message.caption == '/set_night':
        settings['night_photo'] = photo_id
        save_settings(settings)
        bot.reply_to(message, "🌙 **Ночная картинка успешно сохранена!**")
    elif message.caption == '/set_morning':
        settings['morning_photo'] = photo_id
        save_settings(settings)
        bot.reply_to(message, "☀️ **Утренняя картинка успешно сохранена!**")

# --- ОБРАБОТКА CALLBACK-КНОПОК ---

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    if is_banned(user_id):
        bot.answer_callback_query(call.id, "⛔ Вы заблокированы!", show_alert=True)
        return

    if call.data.startswith("spamblock_"):
        bot.answer_callback_query(call.id, "Запрос отправлен заказчику!", show_alert=True)
        msg_id = call.data.replace("spamblock_", "")
        posts_data = load_data(POSTS_FILE)
        
        if msg_id in posts_data:
            creator_id = posts_data[msg_id].get("user_id")
            platform = posts_data[msg_id].get("platform", "Задание")
            payment = posts_data[msg_id].get("payment", "0")
            slot_num = posts_data[msg_id].get("slot_num", "Слот")
            
            executor = call.from_user
            exec_username = f"@{executor.username}" if executor.username else f"ID: {user_id}"
            exec_link = f"https://t.me/{executor.username}" if executor.username else f"tg://user?id={user_id}"

            try:
                alert_text = (
                    f"📩 **НОВЫЙ ОТКЛИК НА ВАШ #{slot_num}!**\n\n"
                    f"Пользователь {exec_username} хочет взять ваше задание:\n"
                    f"📌 **{platform}** за **{payment} руб.**\n\n"
                    f"⚠️ У него **спам-блок**, поэтому напишите ему первыми!"
                )
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(text="💬 Написать исполнителю", url=exec_link))
                bot.send_message(creator_id, alert_text, parse_mode="Markdown", reply_markup=markup)
            except Exception as e:
                print(f"Ошибка отправки уведомления: {e}")
        return

    if call.data == "confirm_publish":
        bot.answer_callback_query(call.id)
        if user_id not in user_creation_data or 'final_text' not in user_creation_data[user_id]:
            bot.send_message(call.message.chat.id, "❌ Ошибка. Начните создание заново.")
            return

        platform_name = user_creation_data[user_id].get('platform', '')
        is_plat_ok, needed_posts = check_platform_cooldown(platform_name)
        if not is_plat_ok:
            time_str, _ = get_next_available_slot_for_platform(platform_name)
            bot.send_message(
                call.message.chat.id, 
                f"⏳ **Платформа «{platform_name}» сейчас находится на кулдауне!**\n"
                f"Нужно, чтобы прошло еще **{needed_posts} поста(ов)** других платформ.\n\n"
                f"💡 Ближайшее свободное время для этой платформы: **{time_str}**.\n"
                "Выберите другое время в сетке или дождитесь окончания кулдауна.",
                reply_markup=get_back_keyboard(),
                parse_mode="Markdown"
            )
            return

        bot.edit_message_text(
            "⏱ **Выберите время публикации по МСК (шаг 20 минут):**\n\nСлот забронируется автоматически, и пост улетит в канал точно в указанное время.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=get_available_slots_keyboard(user_id),
            parse_mode="Markdown"
        )

    elif call.data == "open_slots_menu":
        bot.answer_callback_query(call.id)
        if not check_channel_subscription(user_id):
            bot.send_message(call.message.chat.id, f"❌ Подпишитесь на канал {CHANNEL_ID}!", reply_markup=get_persistent_keyboard())
            return
        if not is_user_active(user_id):
            bot.send_message(call.message.chat.id, f"⛔ У вас нет активного доступа.\nВаш ID: `{user_id}`", parse_mode="Markdown")
            return
        cd = get_cooldown_left(user_id)
        if cd > 0:
            bot.send_message(call.message.chat.id, f"⏳ Кулдаун еще **{format_time(cd)}**.")
            return

        if user_id not in user_creation_data or 'platform' not in user_creation_data[user_id]:
            bot.send_message(call.message.chat.id, "⚠️ Сначала создайте текст поста через **«📝 Выставить пост»**.", reply_markup=get_back_keyboard())
            return

        platform_name = user_creation_data[user_id].get('platform', '')
        is_plat_ok, needed_posts = check_platform_cooldown(platform_name)
        if not is_plat_ok:
            time_str, _ = get_next_available_slot_for_platform(platform_name)
            bot.send_message(
                call.message.chat.id, 
                f"⏳ **Платформа «{platform_name}» на кулдауне!**\n"
                f"Нужно еще **{needed_posts} поста(ов)** других платформ.\n\n"
                f"💡 Ближайшее свободное время: **{time_str}**.",
                reply_markup=get_back_keyboard(),
                parse_mode="Markdown"
            )
            return

        bot.edit_message_text(
            "⏱ **Свободное время / Бронь (шаг 20 минут):**\n\nВыберите доступный слот для публикации:",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=get_available_slots_keyboard(user_id),
            parse_mode="Markdown"
        )

    elif call.data == "refresh_slots":
        bot.answer_callback_query(call.id, "🔄 Слот-сетка обновлена!")
        try:
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=get_available_slots_keyboard(user_id)
            )
        except Exception:
            pass

    elif call.data == "slot_busy":
        bot.answer_callback_query(call.id, "❌ Этот временной слот уже занят другим пользователем. Выберите другое время!", show_alert=True)

    elif call.data == "slot_cooldown_active":
        bot.answer_callback_query(call.id, "⏳ Этот слот попадает под ваш активный кулдаун (2.5 часа). Выберите более позднее время!", show_alert=True)

    elif call.data.startswith("book_slot_"):
        bot.answer_callback_query(call.id)
        timestamp_key = call.data.replace("book_slot_", "")
        
        if user_id not in user_creation_data or 'final_text' not in user_creation_data[user_id]:
            bot.edit_message_text(
                "⚠️ У вас не заполнен текст поста!\nСначала создайте задание через **«📝 Выставить пост»**, а затем выберите время.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=get_back_keyboard(),
                parse_mode="Markdown"
            )
            return

        c_data = user_creation_data[user_id]
        
        is_plat_ok, needed_posts = check_platform_cooldown(c_data['platform'])
        if not is_plat_ok:
            time_str, _ = get_next_available_slot_for_platform(c_data['platform'])
            bot.edit_message_text(
                f"❌ Ошибка: Платформа «{c_data['platform']}» на кулдауне (нужно еще {needed_posts} поста других платформ).\n\n"
                f"💡 Занять время можно будет после: **{time_str}**.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=get_back_keyboard(),
                parse_mode="Markdown"
            )
            return

        scheduled_data = load_data(SCHEDULED_POSTS_FILE)
        if not isinstance(scheduled_data, dict):
            scheduled_data = {}
            
        scheduled_data[timestamp_key] = {
            "user_id": user_id,
            "username": call.from_user.username,
            "final_text": c_data['final_text'],
            "slot_num": c_data['slot_num'],
            "platform": c_data['platform'],
            "payment": c_data['payment']
        }
        save_data(SCHEDULED_POSTS_FILE, scheduled_data)

        dt_formatted = datetime.fromtimestamp(float(timestamp_key), pytz.timezone('Europe/Moscow')).strftime('%H:%M МСК')
        
        success_text = (
            f"✅ **Слот успешно забронирован на {dt_formatted}!**\n\n"
            "Бот автоматически опубликует ваш пост в указанное время минута в минуту.\n\n"
            "🔄 **Если планы поменялись:** Вы можете отменить эту бронь в любой момент до публикации через раздел **«📅 Мои брони»** в главном меню."
        )

        bot.edit_message_text(
            success_text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=get_back_keyboard(),
            parse_mode="Markdown"
        )

    elif call.data == "my_scheduled_posts":
        bot.answer_callback_query(call.id)
        scheduled_data = load_data(SCHEDULED_POSTS_FILE)
        user_bookings = {ts: info for ts, info in scheduled_data.items() if info.get("user_id") == user_id}

        if not user_bookings:
            bot.edit_message_text(
                "📅 **У вас нет активных забронированных постов.**",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=get_back_keyboard(),
                parse_mode="Markdown"
            )
            return

        markup = types.InlineKeyboardMarkup(row_width=1)
        text = "📅 **Ваши активные забронированные слоты:**\n\nНажмите на кнопку отмены под нужным слотом, чтобы снять бронь:\n"
        
        for ts, info in sorted(user_bookings.items(), key=lambda x: float(x[0])):
            dt_str = datetime.fromtimestamp(float(ts), pytz.timezone('Europe/Moscow')).strftime('%d.%m в %H:%M МСК')
            text += f"• **Слот #{info['slot_num']}** на `{dt_str}` ({info['platform']})\n"
            markup.add(types.InlineKeyboardButton(text=f"❌ Отменить бронь #{info['slot_num']} ({dt_str})", callback_data=f"cancel_booking_{ts}"))

        markup.add(types.InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="main_menu"))
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data.startswith("cancel_booking_"):
        bot.answer_callback_query(call.id, "Бронь успешно отменена!")
        ts_to_cancel = call.data.replace("cancel_booking_", "")
        
        scheduled_data = load_data(SCHEDULED_POSTS_FILE)
        if ts_to_cancel in scheduled_data and scheduled_data[ts_to_cancel].get("user_id") == user_id:
            del scheduled_data[ts_to_cancel]
            save_data(SCHEDULED_POSTS_FILE, scheduled_data)

        scheduled_data = load_data(SCHEDULED_POSTS_FILE)
        user_bookings = {ts: info for ts, info in scheduled_data.items() if info.get("user_id") == user_id}

        if not user_bookings:
            bot.edit_message_text(
                "✅ **Бронь отменена.**\n\nУ вас больше нет активных забронированных постов.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=get_back_keyboard(),
                parse_mode="Markdown"
            )
            return

        markup = types.InlineKeyboardMarkup(row_width=1)
        text = "✅ **Бронь отменена.**\n\n📅 **Оставшиеся забронированные слоты:**\n"
        for ts, info in sorted(user_bookings.items(), key=lambda x: float(x[0])):
            dt_str = datetime.fromtimestamp(float(ts), pytz.timezone('Europe/Moscow')).strftime('%d.%m в %H:%M МСК')
            text += f"• **Слот #{info['slot_num']}** на `{dt_str}` ({info['platform']})\n"
            markup.add(types.InlineKeyboardButton(text=f"❌ Отменить бронь #{info['slot_num']} ({dt_str})", callback_data=f"cancel_booking_{ts}"))

        markup.add(types.InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="main_menu"))
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data == "start_create_post" or call.data == "edit_publish":
        bot.answer_callback_query(call.id)
        
        if not check_channel_subscription(user_id):
            bot.send_message(call.message.chat.id, f"❌ Подпишитесь на канал {CHANNEL_ID}!", reply_markup=get_persistent_keyboard())
            return
        if not is_user_active(user_id):
            bot.send_message(call.message.chat.id, f"⛔ У вас нет активного доступа.\nВаш ID: `{user_id}`", parse_mode="Markdown")
            return
        cd = get_cooldown_left(user_id)
        if cd > 0:
            bot.send_message(call.message.chat.id, f"⏳ Кулдаун еще **{format_time(cd)}**.")
            return

        user_creation_data[user_id] = {'step': 1}
        bot.send_message(call.message.chat.id, "📌 **Шаг 1 из 3:**\nВведите площадку (например: *Яндекс Карты, Авито, Пушкинская карта*):", parse_mode="Markdown")

    elif call.data == "repeat_last_post":
        bot.answer_callback_query(call.id)
        if not check_channel_subscription(user_id):
            bot.send_message(call.message.chat.id, f"❌ Подпишитесь на канал {CHANNEL_ID}!", reply_markup=get_persistent_keyboard())
            return
        if not is_user_active(user_id):
            bot.send_message(call.message.chat.id, f"⛔ У вас нет активного доступа.\nВаш ID: `{user_id}`", parse_mode="Markdown")
            return
        cd = get_cooldown_left(user_id)
        if cd > 0:
            bot.send_message(call.message.chat.id, f"⏳ Кулдаун еще **{format_time(cd)}**.")
            return

        if user_id not in user_creation_data or 'final_text' not in user_creation_data[user_id]:
            bot.send_message(call.message.chat.id, "❌ Не найден сохраненный прошлый пост. Нажмите «📝 Выставить пост».", reply_markup=get_back_keyboard())
            return

        c_data = user_creation_data[user_id]
        
        is_plat_ok, needed_posts = check_platform_cooldown(c_data.get('platform', ''))
        if not is_plat_ok:
            time_str, _ = get_next_available_slot_for_platform(c_data.get('platform', ''))
            bot.send_message(
                call.message.chat.id, 
                f"⏳ **Платформа «{c_data.get('platform')}» на кулдауне!**\n"
                f"Нужно еще **{needed_posts} поста(ов)** других платформ перед повтором.\n\n"
                f"💡 Занять время можно будет после: **{time_str}**.",
                reply_markup=get_back_keyboard(),
                parse_mode="Markdown"
            )
            return

        slot_num = get_next_slot_id()
        platform = c_data.get('platform', '')
        payment = c_data.get('payment', '')
        desc = c_data.get('desc', '')

        final_text = (
            f"🔥ГОРЯЧИЙ СЛОТ #{slot_num}\n\n"
            f"❣️ Площадка: {platform}\n"
            f"💵 Оплата: {payment}\n"
            f"😀 Что нужно делать, От себя: {desc}"
        )
        user_creation_data[user_id]['final_text'] = final_text
        user_creation_data[user_id]['slot_num'] = slot_num

        preview_markup = types.InlineKeyboardMarkup(row_width=1)
        preview_markup.add(
            types.InlineKeyboardButton(text="⏱ Забронировать время по МСК", callback_data="confirm_publish"),
            types.InlineKeyboardButton(text="🔄 Повторить прошлый пост", callback_data="repeat_last_post"),
            types.InlineKeyboardButton(text="✏️ Редактировать", callback_data="start_create_post"),
            types.InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_publish")
        )

        bot.send_message(
            call.message.chat.id, 
            f"👁 **ПРЕДПРОСМОТР ВАШЕГО ПОВТОРЕННОГО ПОСТА:**\n\n{final_text}\n\n-------------------\nВсе указано верно?",
            reply_markup=preview_markup,
            parse_mode="Markdown"
        )

    elif call.data == "cancel_publish":
        bot.answer_callback_query(call.id, "Отменено.")
        if user_id in user_creation_data: del user_creation_data[user_id]
        bot.delete_message(call.message.chat.id, call.message.message_id)

    elif call.data == "report_scam":
        bot.answer_callback_query(call.id)
        user_states[user_id] = "waiting_for_report"
        bot.send_message(call.message.chat.id, REPORT_TEXT, parse_mode="Markdown")

    elif call.data == "main_menu":
        bot.answer_callback_query(call.id)
        bot.edit_message_text("👋 Привет! Выберите нужный раздел:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=get_main_menu_keyboard(user_id))

    elif call.data == "show_rules":
        bot.answer_callback_query(call.id)
        bot.edit_message_text(RULES_TEXT, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown", reply_markup=get_back_keyboard())

    elif call.data == "my_profile":
        bot.answer_callback_query(call.id)
        if is_owner(user_id):
            prof_text = "👑 У вас статус **Владельца** (без КД и ограничений)."
        elif is_user_active(user_id):
            users = load_data(DB_FILE)
            u_info = users.get(str(user_id), {})
            exp = u_info.get("expire", 0) if isinstance(u_info, dict) else u_info
            pts = u_info.get("posts", 0) if isinstance(u_info, dict) else 0
            left_days = round((exp - time.time()) / 86400, 1) if exp > time.time() else 0
            cd = get_cooldown_left(user_id)
            cd_str = format_time(cd) if cd > 0 else "Отсутствует (можно выкладывать)"
            
            prof_text = f"👤 **Ваш профиль:**\n\n"
            if left_days > 0: prof_text += f"• Подписка по дням: ~**{left_days} дн.**\n"
            if pts > 0: prof_text += f"• Разовые посты: **{pts} шт.**\n"
            prof_text += f"• Текущий кулдаун: **{cd_str}**"
        else:
            prof_text = "⛔ У вас нет активной подписки или доступных постов."

        bot.edit_message_text(prof_text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=get_back_keyboard())

    elif call.data == "open_admin_help":
        if is_owner(user_id):
            bot.answer_callback_query(call.id)
            bot.edit_message_text(get_admin_help_text(), chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=get_back_keyboard())

# --- ПОШАГОВЫЙ ВВОД И ОБРАБОТКА ВХОДЯЩИХ СООБЩЕНИЙ ---

@bot.message_handler(commands=['cancel'])
def cancel_state(message):
    user_id = message.from_user.id
    if user_id in user_creation_data: del user_creation_data[user_id]
    if user_id in user_states: del user_states[user_id]
    bot.reply_to(message, "Действие отменено.", reply_markup=get_persistent_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "📱 Главное меню")
def handle_menu_button(message):
    bot.send_message(message.chat.id, "👋 Главное меню:", reply_markup=get_main_menu_keyboard(message.from_user.id))

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    if is_banned(user_id): return
    
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("report_"):
        slot_num = args[1].replace("report_", "")
        user_states[user_id] = "waiting_for_report"
        
        custom_report_text = (
            f"🚨 **Оформление жалобы на скам (Слот #{slot_num}):**\n\n"
            "Отправь в ответ **ОДНИМ СООБЩЕНИЕМ**:\n"
            "1. Юзернейм/ID заказчика или номер слота.\n"
            "2. Скриншот вашей работы.\n"
            "3. Скриншот переписки с отказом оплаты.\n\n"
            "👇 **Ждём сообщение ниже:** (для отмены /cancel)"
        )
        bot.send_message(message.chat.id, custom_report_text, parse_mode="Markdown")
        bot.send_message(message.chat.id, "Меню закреплено ниже.", reply_markup=get_persistent_keyboard())
        return

    bot.reply_to(message, "👋 Добро пожаловать!", reply_markup=get_main_menu_keyboard(user_id))
    bot.send_message(message.chat.id, "Меню закреплено ниже.", reply_markup=get_persistent_keyboard())

@bot.message_handler(content_types=['text', 'photo', 'document', 'video', 'animation'])
def handle_inputs(message):
    if message.text and message.text.startswith('/'): return
    user_id = message.from_user.id
    if is_banned(user_id): return

    if user_states.get(user_id) == "waiting_for_report":
        del user_states[user_id]
        bot.reply_to(message, "✅ **Ваша жалоба принята и отправлена администратору на рассмотрение!**", parse_mode="Markdown")
        
        username_str = f"@{message.from_user.username}" if message.from_user.username else f"ID {user_id}"
        admin_alert = f"🚨 **НОВАЯ ЖАЛОБА НА СКАМ** от {username_str} (`{user_id}`):"
        
        for admin_id in OWNER_ID:
            try:
                bot.send_message(admin_id, admin_alert, parse_mode="Markdown")
                bot.forward_message(admin_id, message.chat.id, message.message_id)
            except Exception as e:
                print(f"Ошибка пересылки жалобы админу: {e}")
        return

    if user_id in user_creation_data:
        step = user_creation_data[user_id].get('step', 1)
        text = message.text or message.caption or ""

        if "@" in text or "t.me" in text.lower() or "http" in text.lower():
            bot.reply_to(message, "❌ **Ошибка!** Ссылки и юзернеймы запрещены. Введите заново:")
            return
            
        for word in FORBIDDEN_WORDS:
            if word in text.lower():
                bot.reply_to(message, f"❌ Запрещенное слово ({word}). Введите заново:")
                return

        if step == 1:
            platform_name = text
            
            is_plat_ok, needed_posts = check_platform_cooldown(platform_name)
            if not is_plat_ok:
                time_str, _ = get_next_available_slot_for_platform(platform_name)
                bot.reply_to(
                    message, 
                    f"⏳ **Платформа «{platform_name}» сейчас на кулдауне!**\n"
                    f"Осталось пройти **{needed_posts} поста(ов)** других платформ.\n\n"
                    f"💡 Ориентировочно занять этот слот можно будет после: **{time_str}**.\n\n"
                    "Введите другую площадку или отмените действие через `/cancel`:",
                    parse_mode="Markdown"
                )
                return

            user_creation_data[user_id]['platform'] = platform_name
            user_creation_data[user_id]['step'] = 2
            bot.reply_to(message, "💵 **Шаг 2 из 3:**\nВведите сумму оплаты в рублях (например: *150* или *300 руб*):", parse_mode="Markdown")

        elif step == 2:
            user_creation_data[user_id]['payment'] = text
            user_creation_data[user_id]['step'] = 3
            bot.reply_to(message, "😀 **Шаг 3 из 3:**\nВведите подробное описание задания (что нужно сделать):", parse_mode="Markdown")

        elif step == 3:
            has_keyword = any(kw in text.lower() or kw in user_creation_data[user_id]['platform'].lower() for kw in TASK_KEYWORDS)
            if len(text) < 8 or not has_keyword:
                bot.reply_to(message, "❌ **Слишком короткое или непонятное описание.** Напишите подробнее, что конкретно нужно сделать (отзыв, регистрация, выкуп и т.д.):")
                return

            user_creation_data[user_id]['desc'] = text
            slot_num = get_next_slot_id()
            
            platform = user_creation_data[user_id]['platform']
            payment = user_creation_data[user_id]['payment']
            desc = user_creation_data[user_id]['desc']

            final_text = (
                f"🔥ГОРЯЧИЙ СЛОТ #{slot_num}\n\n"
                f"❣️ Площадка: {platform}\n"
                f"💵 Оплата: {payment}\n"
                f"😀 Что нужно делать, От себя: {desc}"
            )
            
            user_creation_data[user_id]['final_text'] = final_text
            user_creation_data[user_id]['slot_num'] = slot_num

            preview_markup = types.InlineKeyboardMarkup(row_width=1)
            preview_markup.add(
                types.InlineKeyboardButton(text="⏱ Забронировать время по МСК", callback_data="confirm_publish"),
                types.InlineKeyboardButton(text="🔄 Повторить прошлый пост", callback_data="repeat_last_post"),
                types.InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_publish"),
                types.InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_publish")
            )

            bot.reply_to(
                message, 
                f"👁 **ПРЕДПРОСМОТР ВАШЕГО ПОСТА:**\n\n{final_text}\n\n-------------------\nВсе указано верно?",
                reply_markup=preview_markup
            )

# --- ЗАПУСК ПОТОКОВ И ПОЛЛИНГА ---

threading.Thread(target=auto_close_checker, daemon=True).start()
threading.Thread(target=check_expiring_subscriptions_and_cooldowns, daemon=True).start()
threading.Thread(target=backup_scheduler, daemon=True).start()
threading.Thread(target=quiet_hours_channel_announcer, daemon=True).start()
threading.Thread(target=scheduled_posts_checker, daemon=True).start()

if __name__ == '__main__':
    print("Бот запущен с расчетом времени кулдауна платформ...")
    while True:
        try:
            bot.polling(none_stop=True, timeout=30, long_polling_timeout=30, skip_pending=True)
        except Exception as e:
            print(f"Сетевой сбой: {e}. Переподключение через 5 секунд...")
            time.sleep(5)
