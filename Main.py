import os
import re
import json
import time
import zipfile
import telebot
import threading
import urllib.parse
from datetime import datetime, timedelta, timezone
from telebot import types

# --- ОСНОВНЫЕ НАСТРОЙКИ ПОД ТВОЙ КАНАЛ И БОТА ---
TOKEN = '8282256956:AAH-LPJFnh8HYnMHuP8-R1uQGTQ2P-_-pYk'
CHANNEL_ID = '@otzovzaden'
BOT_USERNAME = '@Dengaotziv_bot'
MY_USERNAME = '@premizir'

OWNER_ID = [7605961809]

bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=16)

# Смещение для Москвы (UTC+3)
MSK = timezone(timedelta(hours=3))

# --- ХРАНЕНИЕ ФАЙЛОВ ---
DATA_DIR = '/app/data' if os.path.exists('/app/data') else '.'
DB_FILE = os.path.join(DATA_DIR, 'users.json')
COOLDOWN_FILE = os.path.join(DATA_DIR, 'cooldowns.json')
PLATFORM_HISTORY_FILE = os.path.join(DATA_DIR, 'platform_history.json')  
HISTORY_FILE = os.path.join(DATA_DIR, 'history.json')
POSTS_FILE = os.path.join(DATA_DIR, 'active_posts.json')
SCHEDULED_POSTS_FILE = os.path.join(DATA_DIR, 'scheduled_posts.json')
BAN_FILE = os.path.join(DATA_DIR, 'blacklist.json')
SLOT_COUNTER_FILE = os.path.join(DATA_DIR, 'slot_counter.json')
SETTINGS_FILE = os.path.join(DATA_DIR, 'settings.json')

# ПРАВИЛА
USER_COOLDOWN_TIME = 7200    # 2 часа кулдаун между постами одного юзера
SLOT_STEP_MINUTES = 30       # Шаг сетки 30 минут
MAX_AHEAD_HOURS = 2          # Максимум 2 часа вперед для брони

file_lock = threading.Lock()
user_creation_data = {}  

RULES_TEXT = """⚠️ **ПРАВИЛА ПУБЛИКАЦИИ:**

1. **Шаг сетки:** 30 минут. Бронь доступна максимум на 2 часа вперёд.
2. **Кулдаун платформы:** Если слот на платформе занят, следующий слот для неё блокируется с предложением выбрать время дальше.
3. **Кулдаун пользователя:** Между своими постами необходимо выждать 2 часа.
4. **Обязательна подписка** на наш канал.

🚨 *За нарушение правил доступ аннулируется без возврата средств!*"""

ADMIN_PANEL_TEXT = (
    "🛠 **ПАНЕЛЬ УПРАВЛЕНИЯ ВЛАДЕЛЬЦА:**\n\n"
    "🟢 `/add ID ДНИ [ПОСТЫ]` — Выдать доступ\n"
    "🔴 `/del ID` — Забрать доступ\n"
    "⛔ `/ban ID` / `/unban ID` — Бан/Разбан\n"
    "👤 `/user ID` — Карточка пользователя\n"
    "📋 `/list` — Список подписок\n"
    "📊 `/stats` — Статистика\n"
    "📢 `/broadcast ТЕКСТ` — Рассылка\n"
    "⚡ `/uncd ID` — Сбросить КД\n"
    "📜 `/history` — История постов\n"
    "📦 `/backup` — Бэкап в .zip"
)

# --- БАЗЫ ДАННЫХ ---

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
    except:
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
        elapsed = time.time() - cooldowns[str_id]
        if elapsed < USER_COOLDOWN_TIME:
            return int(USER_COOLDOWN_TIME - elapsed)
    return 0

def set_cooldown(user_id):
    if is_owner(user_id):
        return
    cooldowns = load_data(COOLDOWN_FILE)
    cooldowns[str(user_id)] = time.time()
    save_data(COOLDOWN_FILE, cooldowns)

def normalize_platform_name(platform_text):
    return platform_text.strip().capitalize()

def save_to_history(user_id, username, text):
    history = load_data(HISTORY_FILE)
    if not isinstance(history, list):
        history = []
    history.append({
        "timestamp": datetime.now(MSK).strftime("%d.%m.%Y %H:%M"),
        "user_id": user_id,
        "username": username or "Без username",
        "text": text[:300]
    })
    save_data(HISTORY_FILE, history[-50:])

def format_time(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours} ч. {minutes} мин." if hours > 0 else f"{minutes} мин."

def close_post_in_channel(message_id):
    CLOSED_CARD = (
        "🔒 **[СЛОТ ЗАКРЫТ]**\n\n"
        "━━━━━⬍━━━━━\n"
        "⛔ *Набор на этот слот завершён.*\n\n"
        f"🤖 *Хотите такого же бота в свой канал? Пишите разработчику:* {MY_USERNAME}"
    )
    try:
        bot.edit_message_text(text=CLOSED_CARD, chat_id=CHANNEL_ID, message_id=message_id, parse_mode="Markdown", reply_markup=None)
        return True
    except:
        try:
            bot.delete_message(chat_id=CHANNEL_ID, message_id=message_id)
            bot.send_message(chat_id=CHANNEL_ID, text=CLOSED_CARD, parse_mode="Markdown")
            return True
        except:
            return False

# --- ГЕНЕРАЦИЯ СЛОТОВ ---
def get_available_slots_keyboard(user_id, platform_name):
    now = datetime.now(MSK)
    
    scheduled_data = load_data(SCHEDULED_POSTS_FILE)
    if not isinstance(scheduled_data, dict):
        scheduled_data = {}

    norm_platform = normalize_platform_name(platform_name)
    cd_left = get_cooldown_left(user_id)
    
    # Проверяем брони самого пользователя в расписании, чтобы он не забивал всё подряд
    user_latest_booking_ts = 0
    for ts_str, p_info in scheduled_data.items():
        if p_info.get("user_id") == user_id:
            if float(ts_str) > user_latest_booking_ts:
                user_latest_booking_ts = float(ts_str)
    
    # Если у юзера есть бронь, кулдаун от нее действует еще 2 часа (USER_COOLDOWN_TIME)
    booking_cd_expire = user_latest_booking_ts + USER_COOLDOWN_TIME if user_latest_booking_ts > 0 else 0
    earliest_available_time = max(now.timestamp() + cd_left, booking_cd_expire)

    minute = now.minute
    rem = minute % SLOT_STEP_MINUTES
    add_min = SLOT_STEP_MINUTES - rem if rem != 0 else SLOT_STEP_MINUTES
    start_dt = now + timedelta(minutes=add_min)
    start_dt = start_dt.replace(second=0, microsecond=0)

    markup = types.InlineKeyboardMarkup(row_width=2)
    slot_dt = start_dt
    slots_count = 0
    max_end_time = now + timedelta(hours=MAX_AHEAD_HOURS)

    while slot_dt <= max_end_time and slots_count < 6:
        slot_str = slot_dt.strftime("%H:%M")
        timestamp_key = str(int(slot_dt.timestamp()))
        slot_timestamp = slot_dt.timestamp()
        
        is_slot_busy = timestamp_key in scheduled_data
        busy_platform = scheduled_data[timestamp_key].get("platform", "") if is_slot_busy else ""

        prev_dt = slot_dt - timedelta(minutes=SLOT_STEP_MINUTES)
        prev_key = str(int(prev_dt.timestamp()))
        is_platform_cooldown = prev_key in scheduled_data and normalize_platform_name(scheduled_data[prev_key].get("platform", "")) == norm_platform

        if is_slot_busy:
            btn_text = f"❌ {slot_str} ({busy_platform})"
            callback_data = "slot_busy"
        elif is_platform_cooldown:
            btn_text = f"⏳ {slot_str} (КД платф.)"
            callback_data = "slot_platform_cooldown"
        elif slot_timestamp < earliest_available_time:
            btn_text = f"⏳ {slot_str} (Ваш КД)"
            callback_data = "slot_user_cooldown"
        else:
            btn_text = f"🟢 {slot_str}"
            callback_data = f"book_slot_{timestamp_key}"
            slots_count += 1
            
        markup.add(types.InlineKeyboardButton(text=btn_text, callback_data=callback_data))
        slot_dt += timedelta(minutes=SLOT_STEP_MINUTES)

    markup.add(types.InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_slots"))
    markup.add(types.InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_publish"))
    return markup

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
                                types.InlineKeyboardButton(text="🚨 Пожаловаться", url=f"https://t.me/{clean_bot_username}?start=report_{slot_num}")
                            )
                            bot.edit_message_reply_markup(chat_id=CHANNEL_ID, message_id=published_msg.message_id, reply_markup=markup)

                            consume_post_credit(user_id)
                            set_cooldown(user_id)
                            save_to_history(user_id, username, final_text)
                            
                            confirm_markup = types.InlineKeyboardMarkup(row_width=2)
                            confirm_markup.add(
                                types.InlineKeyboardButton(text="🔄 Повторить пост", callback_data="repeat_last_post"),
                                types.InlineKeyboardButton(text="📝 Новый пост", callback_data="start_create_post")
                            )
                            confirm_markup.add(types.InlineKeyboardButton(text="📱 Главное меню", callback_data="main_menu"))

                            confirm_msg = bot.send_message(
                                user_id,
                                f"🚀 **Ваш забронированный слот #{slot_num} успешно опубликован в канале!**",
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
                            print(f"Ошибка автоотправки: {e}")

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
                if now - p_info.get("created_at", 0) >= 7200:
                    close_post_in_channel(int(p_id))
                    del posts_data[p_id]
                    changed = True
            if changed:
                save_data(POSTS_FILE, posts_data)
        except:
            pass
        time.sleep(15)

def backup_scheduler():
    while True:
        # Ждем ровно 24 часа (86400 секунд) перед каждым новым бэкапом
        time.sleep(86400)
        try:
            backup_filename = os.path.join(DATA_DIR, f"backup_{datetime.now(MSK).strftime('%Y%m%d_%H%M%S')}.zip")
            with zipfile.ZipFile(backup_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(DATA_DIR):
                    for file in files:
                        if file.endswith('.json'):
                            zipf.write(os.path.join(root, file), arcname=file)
            if OWNER_ID:
                with open(backup_filename, 'rb') as doc:
                    bot.send_document(OWNER_ID[0], doc, caption="📦 Авто-бэкап (раз в сутки)", parse_mode="Markdown")
            if os.path.exists(backup_filename):
                os.remove(backup_filename)
        except:
            pass

# --- КЛАВИАТУРЫ ---

def get_persistent_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("📱 Главное меню"))
    return markup

def get_main_menu_keyboard(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(text="📝 Выставить пост", callback_data="start_create_post"),
        types.InlineKeyboardButton(text="📖 Правила", callback_data="show_rules"),
        types.InlineKeyboardButton(text="⏳ Мой профиль / КД", callback_data="my_profile"),
        types.InlineKeyboardButton(text="📅 Мои брони", callback_data="my_scheduled_posts"),
        types.InlineKeyboardButton(text="🚨 Пожаловаться на скам", callback_data="report_scam")
    )
    if is_owner(user_id):
        markup.add(types.InlineKeyboardButton(text="🛠 Админ-панель", callback_data="open_admin_panel"))
    return markup

def get_back_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="main_menu"))
    return markup

def get_admin_panel_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(text="📅 Все брони по платформам", callback_data="admin_manage_bookings"),
        types.InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="main_menu")
    )
    return markup

# --- АДМИН КОМАНДЫ ---

@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    if not is_owner(message.from_user.id): return
    bot.reply_to(message, ADMIN_PANEL_TEXT, parse_mode="Markdown", reply_markup=get_admin_panel_keyboard())

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
        bot.reply_to(message, f"✅ Доступ для ID `{target_id}` выдан на {days} дн. и {posts} постов!", parse_mode="Markdown")
        try:
            bot.send_message(int(target_id), "🎉 **Вам выдан доступ к боту!** Нажмите /start", reply_markup=get_persistent_keyboard())
        except:
            pass
    except:
        bot.reply_to(message, "Формат: `/add ID ДНИ [ПОСТЫ]`", parse_mode="Markdown")

@bot.message_handler(commands=['del'])
def del_user(message):
    if not is_owner(message.from_user.id): return
    try:
        target_id = str(message.text.split()[1])
        users = load_data(DB_FILE)
        if target_id in users:
            del users[target_id]
            save_data(DB_FILE, users)
            bot.reply_to(message, f"🗑 Доступ у пользователя `{target_id}` успешно забран.", parse_mode="Markdown")
        else:
            bot.reply_to(message, f"⚠️ Пользователь `{target_id}` не найден в базе.", parse_mode="Markdown")
    except:
        bot.reply_to(message, "Формат: `/del ID`", parse_mode="Markdown")

@bot.message_handler(commands=['ban'])
def ban_user(message):
    if not is_owner(message.from_user.id): return
    try:
        target_id = str(message.text.split()[1])
        b = load_data(BAN_FILE)
        if target_id not in b:
            b.append(target_id)
            save_data(BAN_FILE, b)
        bot.reply_to(message, f"⛔ Пользователь `{target_id}` забанен.", parse_mode="Markdown")
    except:
        bot.reply_to(message, "Формат: `/ban ID`", parse_mode="Markdown")

@bot.message_handler(commands=['unban'])
def unban_user(message):
    if not is_owner(message.from_user.id): return
    try:
        target_id = str(message.text.split()[1])
        b = load_data(BAN_FILE)
        if target_id in b:
            b.remove(target_id)
            save_data(BAN_FILE, b)
        bot.reply_to(message, f"✅ Пользователь `{target_id}` разбанен.", parse_mode="Markdown")
    except:
        bot.reply_to(message, "Формат: `/unban ID`", parse_mode="Markdown")

@bot.message_handler(commands=['user'])
def user_card(message):
    if not is_owner(message.from_user.id): return
    try:
        target_id = str(message.text.split()[1])
        users = load_data(DB_FILE)
        b = load_data(BAN_FILE)
        is_b = target_id in b
        
        if target_id in users:
            u_data = users[target_id]
            if isinstance(u_data, dict):
                exp = u_data.get("expire", 0)
                exp_str = datetime.fromtimestamp(exp, MSK).strftime('%d.%m.%Y %H:%M') if exp > 0 else "Бессрочно / Нет"
                posts = u_data.get("posts", 0)
            else:
                exp_str = datetime.fromtimestamp(u_data, MSK).strftime('%d.%m.%Y %H:%M')
                posts = 0
            bot.reply_to(message, f"👤 **Карточка пользователя `{target_id}`:**\n• Бан: `{'Да' if is_b else 'Нет'}`\n• Подписка до: `{exp_str}`\n• Остаток постов: `{posts}`", parse_mode="Markdown")
        else:
            bot.reply_to(message, f"👤 Пользователь `{target_id}` не найден в базе активных подписок. Бан: `{'Да' if is_b else 'Нет'}`", parse_mode="Markdown")
    except:
        bot.reply_to(message, "Формат: `/user ID`", parse_mode="Markdown")

@bot.message_handler(commands=['list'])
def list_users(message):
    if not is_owner(message.from_user.id): return
    users = load_data(DB_FILE)
    if not users:
        bot.reply_to(message, "📋 Список подписок пуст.")
        return
    text = "📋 **Список пользователей с доступом:**\n\n"
    for uid, data in users.items():
        if isinstance(data, dict):
            exp = data.get("expire", 0)
            exp_str = datetime.fromtimestamp(exp, MSK).strftime('%d.%m.%Y') if exp > 0 else "Без срока"
            posts = data.get("posts", 0)
            text += f"• `{uid}`: До `{exp_str}`, постов: `{posts}`\n"
        else:
            text += f"• `{uid}`\n"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['stats'])
def stats_cmd(message):
    if not is_owner(message.from_user.id): return
    users = load_data(DB_FILE)
    banned = load_data(BAN_FILE)
    sched = load_data(SCHEDULED_POSTS_FILE)
    history = load_data(HISTORY_FILE)
    
    text = (
        "📊 **Статистика бота:**\n\n"
        f"• Активных пользователей в базе: `{len(users)}`\n"
        f"• Заблокированных: `{len(banned)}`\n"
        f"• Активных броней в сетке: `{len(sched)}`\n"
        f"• Всего записей в истории: `{len(history)}`"
    )
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['broadcast'])
def broadcast_cmd(message):
    if not is_owner(message.from_user.id): return
    text_to_send = message.text.replace('/broadcast', '').strip()
    if not text_to_send:
        bot.reply_to(message, "Формат: `/broadcast ТЕКСТ`", parse_mode="Markdown")
        return
    
    users = load_data(DB_FILE)
    success = 0
    fail = 0
    for uid in users:
        try:
            bot.send_message(int(uid), f"📢 **Сообщение от администратора:**\n\n{text_to_send}", parse_mode="Markdown")
            success += 1
            time.sleep(0.1)
        except:
            fail += 1
    bot.reply_to(message, f"📢 Рассылка завершена!\n✅ Успешно: `{success}`\n❌ Ошибок: `{fail}`", parse_mode="Markdown")

@bot.message_handler(commands=['uncd'])
def uncd_cmd(message):
    if not is_owner(message.from_user.id): return
    try:
        target_id = str(message.text.split()[1])
        cooldowns = load_data(COOLDOWN_FILE)
        if target_id in cooldowns:
            del cooldowns[target_id]
            save_data(COOLDOWN_FILE, cooldowns)
            bot.reply_to(message, f"⚡ Кулдаун для пользователя `{target_id}` успешно сброшен!", parse_mode="Markdown")
        else:
            bot.reply_to(message, f"⚠️ У пользователя `{target_id}` не было активного кулдауна.", parse_mode="Markdown")
    except:
        bot.reply_to(message, "Формат: `/uncd ID`", parse_mode="Markdown")

@bot.message_handler(commands=['history'])
def history_cmd(message):
    if not is_owner(message.from_user.id): return
    history = load_data(HISTORY_FILE)
    if not history:
        bot.reply_to(message, "📜 История постов пуста.")
        return
    text = "📜 **Последние опубликованные посты:**\n\n"
    for item in history[-10:]:
        text += f"▪️ `{item['timestamp']}` (ID: `{item['user_id']}`)\n{item['text'][:100]}...\n\n"
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['backup'])
def backup_cmd(message):
    if not is_owner(message.from_user.id): return
    try:
        backup_filename = os.path.join(DATA_DIR, f"backup_{datetime.now(MSK).strftime('%Y%m%d_%H%M%S')}.zip")
        with zipfile.ZipFile(backup_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(DATA_DIR):
                for file in files:
                    if file.endswith('.json'):
                        zipf.write(os.path.join(root, file), arcname=file)
        with open(backup_filename, 'rb') as doc:
            bot.send_document(message.chat.id, doc, caption="📦 Бэкап баз данных", parse_mode="Markdown")
        if os.path.exists(backup_filename):
            os.remove(backup_filename)
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка создания бэкапа: {e}")

# --- ОБРАБОТКА CALLBACK ---

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    try:
        bot.answer_callback_query(call.id)
    except:
        pass

    if is_banned(user_id):
        return

    if call.data == "start_create_post":
        if not check_channel_subscription(user_id):
            bot.send_message(call.message.chat.id, f"❌ Подпишитесь на канал {CHANNEL_ID}!", reply_markup=get_persistent_keyboard())
            return
        if not is_user_active(user_id):
            bot.send_message(call.message.chat.id, f"⛔ У вас нет активного доступа. Ваш ID: `{user_id}`", parse_mode="Markdown")
            return
        cd = get_cooldown_left(user_id)
        if cd > 0:
            bot.send_message(call.message.chat.id, f"⏳ Кулдаун между постами: еще **{format_time(cd)}**.")
            return

        user_creation_data[user_id] = {'step': 1}
        bot.edit_message_text(
            "📌 **Шаг 1 из 3:**\nВведите название платформы (например: *Яндекс Карты*, *Авито* и т.д.):",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )

    elif call.data == "confirm_publish":
        if user_id not in user_creation_data or 'final_text' not in user_creation_data[user_id]:
            bot.send_message(call.message.chat.id, "❌ Ошибка. Начните создание заново.")
            return

        platform_name = user_creation_data[user_id].get('platform', 'Задание')
        bot.edit_message_text(
            "⏱ **Выберите время публикации по МСК (на ближайшие 2 часа, шаг 30 мин):**",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=get_available_slots_keyboard(user_id, platform_name),
            parse_mode="Markdown"
        )

    elif call.data == "refresh_slots":
        bot.answer_callback_query(call.id, "🔄 Сетка обновлена!")
        try:
            platform_name = user_creation_data.get(user_id, {}).get('platform', 'Задание')
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=get_available_slots_keyboard(user_id, platform_name)
            )
        except:
            pass

    elif call.data == "slot_busy":
        bot.answer_callback_query(call.id, "❌ Этот временной слот уже занят!", show_alert=True)

    elif call.data == "slot_platform_cooldown":
        bot.answer_callback_query(call.id, "⏳ Нельзя забронировать: предыдущий слот занят этой же платформой. Выберите время дальше!", show_alert=True)

    elif call.data == "slot_user_cooldown":
        bot.answer_callback_query(call.id, "⏳ Этот слот попадает под ваш персональный кулдаун (или уже имеющуюся бронь)!", show_alert=True)

    elif call.data.startswith("book_slot_"):
        timestamp_key = call.data.replace("book_slot_", "")
        if user_id not in user_creation_data or 'final_text' not in user_creation_data[user_id]:
            bot.edit_message_text("⚠️ Ошибка данных. Создайте пост заново.", chat_id=call.message.chat.id, message_id=call.message.message_id)
            return

        c_data = user_creation_data[user_id]
        scheduled_data = load_data(SCHEDULED_POSTS_FILE)
        
        scheduled_data[timestamp_key] = {
            "user_id": user_id,
            "username": call.from_user.username,
            "final_text": c_data['final_text'],
            "slot_num": c_data['slot_num'],
            "platform": c_data['platform'],
            "payment": c_data['payment']
        }
        save_data(SCHEDULED_POSTS_FILE, scheduled_data)

        dt_formatted = datetime.fromtimestamp(float(timestamp_key), MSK).strftime('%H:%M МСК')
        bot.edit_message_text(
            f"✅ **Слот успешно забронирован на {dt_formatted}!**\nБот опубликует его автоматически.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=get_back_keyboard(),
            parse_mode="Markdown"
        )

    elif call.data == "my_scheduled_posts":
        scheduled_data = load_data(SCHEDULED_POSTS_FILE)
        user_bookings = {ts: info for ts, info in scheduled_data.items() if info.get("user_id") == user_id}

        if not user_bookings:
            bot.edit_message_text("📅 **У вас нет активных броней.**", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=get_back_keyboard(), parse_mode="Markdown")
            return

        markup = types.InlineKeyboardMarkup(row_width=1)
        text = "📅 **Ваши активные брони:**\n\n"
        for ts, info in sorted(user_bookings.items(), key=lambda x: float(x[0])):
            dt_str = datetime.fromtimestamp(float(ts), MSK).strftime('%d.%m в %H:%M МСК')
            text += f"• #{info['slot_num']} на `{dt_str}` ({info['platform']})\n"
            markup.add(types.InlineKeyboardButton(text=f"❌ Отменить бронь #{info['slot_num']}", callback_data=f"cancel_booking_{ts}"))
        markup.add(types.InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="main_menu"))
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data.startswith("cancel_booking_"):
        bot.answer_callback_query(call.id, "Бронь отменена!")
        ts_to_cancel = call.data.replace("cancel_booking_", "")
        scheduled_data = load_data(SCHEDULED_POSTS_FILE)
        if ts_to_cancel in scheduled_data:
            if scheduled_data[ts_to_cancel].get("user_id") == user_id or is_owner(user_id):
                del scheduled_data[ts_to_cancel]
                save_data(SCHEDULED_POSTS_FILE, scheduled_data)
        
        if is_owner(user_id) and "admin" in call.message.text.lower():
            call.data = "admin_manage_bookings"
            callback_handler(call)
        else:
            call.data = "my_scheduled_posts"
            callback_handler(call)

    elif call.data == "open_admin_panel":
        if not is_owner(user_id): return
        bot.edit_message_text(ADMIN_PANEL_TEXT, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")

    elif call.data == "admin_manage_bookings":
        if not is_owner(user_id): return
        scheduled_data = load_data(SCHEDULED_POSTS_FILE)
        if not scheduled_data:
            bot.edit_message_text("📅 Активных броней в системе нет.", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
            return

        markup = types.InlineKeyboardMarkup(row_width=1)
        text = "📅 **Все активные брони:**\n\n"
        for ts, info in sorted(scheduled_data.items(), key=lambda x: float(x[0])):
            dt_str = datetime.fromtimestamp(float(ts), MSK).strftime('%d.%m в %H:%M МСК')
            text += f"• Бронь #{info['slot_num']} на `{dt_str}` ({info['platform']})\n"
            markup.add(types.InlineKeyboardButton(text=f"❌ Снять бронь #{info['slot_num']} ({dt_str})", callback_data=f"cancel_booking_{ts}"))
        markup.add(types.InlineKeyboardButton(text="⬅️ Назад в админ-панель", callback_data="open_admin_panel"))
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data == "cancel_publish":
        if user_id in user_creation_data: del user_creation_data[user_id]
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass

    elif call.data == "main_menu":
        bot.edit_message_text("👋 Главное меню:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=get_main_menu_keyboard(user_id))

    elif call.data == "show_rules":
        bot.edit_message_text(RULES_TEXT, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown", reply_markup=get_back_keyboard())

    elif call.data == "my_profile":
        if is_owner(user_id):
            prof_text = "👑 У вас статус **Владельца**."
        elif is_user_active(user_id):
            cd = get_cooldown_left(user_id)
            cd_str = format_time(cd) if cd > 0 else "Отсутствует"
            prof_text = f"👤 **Ваш профиль:**\n• Кулдаун между постами: **{cd_str}**"
        else:
            prof_text = "⛔ У вас нет активного доступа."
        bot.edit_message_text(prof_text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=get_back_keyboard(), parse_mode="Markdown")

    elif call.data == "report_scam":
        bot.edit_message_text(
            f"🚨 Если вы столкнулись со скамом или нарушением, напишите администратору: {MY_USERNAME}",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=get_back_keyboard(),
            parse_mode="Markdown"
        )

# --- ТЕКСТОВЫЕ ВВОДЫ ---

@bot.message_handler(commands=['cancel'])
def cancel_cmd(message):
    user_id = message.from_user.id
    if user_id in user_creation_data: del user_creation_data[user_id]
    bot.reply_to(message, "Действие отменено.", reply_markup=get_persistent_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "📱 Главное меню")
def handle_menu_btn(message):
    bot.send_message(message.chat.id, "👋 Главное меню:", reply_markup=get_main_menu_keyboard(message.from_user.id))

@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    if is_banned(user_id): return
    bot.reply_to(message, "👋 Добро пожаловать!", reply_markup=get_main_menu_keyboard(user_id))
    bot.send_message(message.chat.id, "Меню закреплено ниже.", reply_markup=get_persistent_keyboard())

@bot.message_handler(content_types=['text'])
def text_handler(message):
    if message.text.startswith('/'): return
    user_id = message.from_user.id
    if is_banned(user_id): return
    text = message.text.strip()

    if user_id in user_creation_data:
        step = user_creation_data[user_id].get('step', 1)

        if step == 1:
            user_creation_data[user_id]['platform'] = text
            user_creation_data[user_id]['step'] = 2
            bot.reply_to(message, "💵 **Шаг 2 из 3:**\nВведите сумму оплаты в рублях (например: *150*):", parse_mode="Markdown")

        elif step == 2:
            user_creation_data[user_id]['payment'] = text
            user_creation_data[user_id]['step'] = 3
            bot.reply_to(message, "😀 **Шаг 3 из 3:**\nВведите подробное описание задания:", parse_mode="Markdown")

        elif step == 3:
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
                types.InlineKeyboardButton(text="⏱ Выбрать время брони (до 2ч вперёд)", callback_data="confirm_publish"),
                types.InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_publish")
            )

            bot.reply_to(message, f"👁 **ПРЕДПРОСМОТР ПОСТА:**\n\n{final_text}\n\nВсе верно?", reply_markup=preview_markup)

# --- ЗАПУСК ПОТОКОВ ---

threading.Thread(target=auto_close_checker, daemon=True).start()
threading.Thread(target=backup_scheduler, daemon=True).start()
threading.Thread(target=scheduled_posts_checker, daemon=True).start()

if __name__ == '__main__':
    print("Бот запущен и полностью оптимизирован...")
    while True:
        try:
            bot.polling(none_stop=True, timeout=30, long_polling_timeout=30, skip_pending=True)
        except Exception as e:
            print(f"Сбой: {e}. Переподключение...")
            time.sleep(5)
