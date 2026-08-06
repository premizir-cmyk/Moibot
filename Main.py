import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
import threading
import time
import json
import os
import re
from datetime import datetime

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
NOTIFIED_FILE = os.path.join(DATA_DIR, 'notified.json')
HISTORY_FILE = os.path.join(DATA_DIR, 'history.json')
POSTS_FILE = os.path.join(DATA_DIR, 'active_posts.json')
CD_NOTIFIED_FILE = os.path.join(DATA_DIR, 'cd_notified.json')

COOLDOWN_TIME = 9000    # 2.5 часа кулдаун между постами (в секундах)
AUTO_CLOSE_TIME = 7200  # 2 часа до автозакрытия поста (в секундах)

# Список запрещенных скам-слов
FORBIDDEN_WORDS = ['казино', '1win', 'крипта', 'трейдинг', 'пирамида', 'darknet', 'нарко', 'взлом']

# Потокобезопасность для работы с JSON
file_lock = threading.Lock()

# --- ШАБЛОНЫ И ПРАВИЛА ---
TEMPLATE_TEXT = """🔥ГОРЯЧИЙ СЛОТ

❣️ Площадка: 
💵 Оплата: 
😀 Что нужно делать, От себя: """

RULES_TEXT = """⚠️ **ПРАВИЛА ПУБЛИКАЦИИ:**

1. **Строго по шаблону!** Любой сторонний текст до или после шаблона запрещен.
2. **Запрещены юзернеймы, внешние ссылки и скам!** Для связи используется только кнопка под постом.
3. **Кулдаун:** Между постами 2 часа 30 минут.
4. **Обязательна подписка** на наш канал.

🚨 *За нарушение правил доступ аннулируется без возврата средств!*"""

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def load_data(filename):
    with file_lock:
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Ошибка чтения {filename}: {e}")
                return {} if not filename.endswith('history.json') else []
        return {} if not filename.endswith('history.json') else []

def save_data(filename, data):
    with file_lock:
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка сохранения {filename}: {e}")

def is_owner(user_id):
    return user_id in OWNER_ID

def check_channel_subscription(user_id):
    """Проверка подписки на основной канал"""
    if is_owner(user_id):
        return True
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception:
        return True  # В случае ошибки API пропускаем

def is_user_active(user_id):
    if is_owner(user_id):
        return True
    users = load_data(DB_FILE)
    str_id = str(user_id)
    if str_id in users:
        data = users[str_id]
        if isinstance(data, dict):
            exp_time = data.get("expire", 0)
            posts_left = data.get("posts", 0)
            if (exp_time > 0 and time.time() < exp_time) or posts_left > 0:
                return True
        elif isinstance(data, (int, float)):  # Поддержка старого формата баз
            if time.time() < data:
                return True
            else:
                del users[str_id]
                save_data(DB_FILE, users)
    return False

def consume_post_credit(user_id):
    """Списывает 1 пост, если у пользователя поштучная оплата"""
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
    
    # Сбрасываем флаг уведомления о выходе из КД
    cd_notified = load_data(CD_NOTIFIED_FILE)
    if str(user_id) in cd_notified:
        del cd_notified[str(user_id)]
        save_data(CD_NOTIFIED_FILE, cd_notified)

def reset_cooldown(user_id):
    cooldowns = load_data(COOLDOWN_FILE)
    str_id = str(user_id)
    if str_id in cooldowns:
        del cooldowns[str_id]
        save_data(COOLDOWN_FILE, cooldowns)

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
    if hours > 0:
        return f"{hours} ч. {minutes} мин."
    else:
        return f"{minutes} мин."

def validate_template_strict(text):
    if not text:
        return False, "Текст поста пуст."
    
    clean_text = text.strip()

    if "Писать строго сюда" in clean_text:
        return False, "Использована устаревшая строка 'Писать строго сюда'."

    if "@" in clean_text or "t.me" in clean_text.lower() or "telegram.me" in clean_text.lower() or "http" in clean_text.lower():
        return False, "Запрещено указывать юзернеймы (@) или ссылки в тексте поста!"

    # Антискам проверка
    for word in FORBIDDEN_WORDS:
        if word in clean_text.lower():
            return False, f"Текст содержит запрещенное слово/тематику ({word})!"

    pattern = r"^🔥ГОРЯЧИЙ СЛОТ\s+❣️ Площадка:\s*(.+?)\s+💵 Оплата:\s*(.+?)\s+😀 Что нужно делать, От себя:\s*(.+)$"
    
    match = re.match(pattern, clean_text, re.DOTALL)
    if not match:
        return False, "Нарушена структура шаблона или добавлен лишний текст снаружи шаблона."
        
    platform, payment, description = match.groups()
    if not platform.strip() or not payment.strip() or not description.strip():
        return False, "Все поля шаблона должны быть заполнены!"

    return True, "OK"

# --- ЛОГИКА ЗАКРЫТИЯ ПОСТА В КАНАЛЕ ---

def close_post_in_channel(message_id):
    CLOSED_CARD = (
        "🔒 **[СЛОТ ЗАКРЫТ]**\n\n"
        "━━━━━⬍━━━━━\n"
        "⛔ *Набор на этот слот завершён.*\n"
        "🔔 Включите уведомления в канале, чтобы не пропустить новые предложения!\n\n"
        f"🤖 *Хотите такого же бота в свой канал? Пишите разработчику:* {MY_USERNAME}"
    )

    try:
        bot.edit_message_text(
            text=CLOSED_CARD,
            chat_id=CHANNEL_ID,
            message_id=message_id,
            parse_mode="Markdown",
            reply_markup=None
        )
        return True
    except Exception:
        try:
            bot.delete_message(chat_id=CHANNEL_ID, message_id=message_id)
            bot.send_message(
                chat_id=CHANNEL_ID,
                text=CLOSED_CARD,
                parse_mode="Markdown"
            )
            return True
        except Exception as e:
            print(f"Ошибка при удалении/очистке поста {message_id}: {e}")
            try:
                bot.edit_message_caption(
                    caption=CLOSED_CARD,
                    chat_id=CHANNEL_ID,
                    message_id=message_id,
                    parse_mode="Markdown",
                    reply_markup=None
                )
                return True
            except:
                return False

# --- ФОНОВЫЕ ПОТОКИ ---

def auto_close_checker():
    while True:
        try:
            posts_data = load_data(POSTS_FILE)
            now = time.time()
            changed = False
            
            for p_id, p_info in list(posts_data.items()):
                created_at = p_info.get("created_at", 0)
                if now - created_at >= AUTO_CLOSE_TIME:
                    msg_id = int(p_id)
                    close_post_in_channel(msg_id)
                    del posts_data[p_id]
                    changed = True
                    
            if changed:
                save_data(POSTS_FILE, posts_data)
                
        except Exception as e:
            print(f"Ошибка автозакрытия: {e}")
            
        time.sleep(15)

def check_expiring_subscriptions_and_cooldowns():
    """Проверка подписок и отправка уведомления при выходе из КД"""
    while True:
        try:
            users = load_data(DB_FILE)
            notified = load_data(NOTIFIED_FILE)
            cooldowns = load_data(COOLDOWN_FILE)
            cd_notified = load_data(CD_NOTIFIED_FILE)
            now = time.time()
            
            # 1. Проверка закінчення подписки
            for u_id, u_info in list(users.items()):
                exp_time = u_info.get("expire", 0) if isinstance(u_info, dict) else u_info
                time_left = exp_time - now
                if 0 < time_left <= 86400 and u_id not in notified:
                    try:
                        bot.send_message(
                            int(u_id), 
                            f"⚠️ **Внимание!** Ваша подписка закончится через 24 часа.\nДля продления пишите {MY_USERNAME}",
                            parse_mode="Markdown"
                        )
                        notified[u_id] = True
                        save_data(NOTIFIED_FILE, notified)
                    except:
                        notified[u_id] = True
                        save_data(NOTIFIED_FILE, notified)

            # 2. Уведомление об окончании кулдауна
            for u_id, last_time in list(cooldowns.items()):
                if now - last_time >= COOLDOWN_TIME and u_id not in cd_notified:
                    try:
                        bot.send_message(
                            int(u_id),
                            "⚡ **Твой кулдаун окончен!**\nВы можете опубликовать новый слот прямо сейчас.",
                            parse_mode="Markdown"
                        )
                    except:
                        pass
                    cd_notified[u_id] = True
                    save_data(CD_NOTIFIED_FILE, cd_notified)

        except Exception as e:
            print(f"Ошибка фона: {e}")
            
        time.sleep(60)

# --- КЛАВИАТУРЫ И МЕНЮ ---

def get_main_menu_keyboard(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(text="📋 Шаблон поста", callback_data="get_template"),
        types.InlineKeyboardButton(text="📖 Правила", callback_data="show_rules"),
        types.InlineKeyboardButton(text="⏳ Мой профиль / КД", callback_data="my_profile")
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
        "🟢 `/add ID ДНИ [ПОСТЫ]` — Выдать доступ (Пример: `/add 12345 30` или `/add 12345 0 5` на 5 постов)\n"
        "🔴 `/del ID` — Забрать доступ у пользователя\n"
        "👤 `/user ID` — Карточка пользователя\n"
        "📋 `/list` — Список активных подписок\n"
        "📊 `/stats` — Статистика бота\n"
        "📢 `/broadcast ТЕКСТ` — Рассылка пользователям\n"
        "⚡ `/uncd ID` — Сбросить кулдаун юзеру\n"
        "📜 `/history` — Посмотреть последние посты\n"
    )

# --- АДМИН-КОМАНДЫ ---

@bot.message_handler(commands=['adminhelp'])
def admin_help_cmd(message):
    if not is_owner(message.from_user.id):
        return
    bot.reply_to(message, get_admin_help_text(), parse_mode="Markdown")

@bot.message_handler(commands=['add'])
def add_user(message):
    if not is_owner(message.from_user.id):
        return
    try:
        args = message.text.split()
        target_id = str(args[1])
        days = int(args[2])
        posts = int(args[3]) if len(args) > 3 else 0

        users = load_data(DB_FILE)
        exp_time = time.time() + (days * 86400) if days > 0 else 0
        
        users[target_id] = {
            "expire": exp_time,
            "posts": posts
        }
        save_data(DB_FILE, users)
        
        notified = load_data(NOTIFIED_FILE)
        if target_id in notified:
            del notified[target_id]
            save_data(NOTIFIED_FILE, notified)

        msg_text = f"✅ Доступ для ID `{target_id}` успешно обновлен!\n"
        if days > 0:
            msg_text += f"• Подписка: **{days} дн.**\n"
        if posts > 0:
            msg_text += f"• Разовые посты: **{posts} шт.**"

        bot.reply_to(message, msg_text, parse_mode="Markdown")
        try:
            bot.send_message(int(target_id), f"🎉 **Вам обновлен доступ к боту!**\n\n{msg_text}\n\nНажмите /start для начала.")
        except:
            pass
    except Exception:
        bot.reply_to(message, "❌ Формат: `/add ID ДНИ [ПОСТЫ]`\nПример на дни: `/add 12345 30`\nПример на посты: `/add 12345 0 5`", parse_mode="Markdown")

@bot.message_handler(commands=['del'])
def del_user(message):
    if not is_owner(message.from_user.id):
        return
    try:
        target_id = str(message.text.split()[1])
        users = load_data(DB_FILE)
        if target_id in users:
            del users[target_id]
            save_data(DB_FILE, users)
            bot.reply_to(message, f"⛔ Доступ для ID `{target_id}` аннулирован.", parse_mode="Markdown")
        else:
            bot.reply_to(message, "Юзер не найден в базе.")
    except:
        bot.reply_to(message, "Формат: `/del ID`", parse_mode="Markdown")

@bot.message_handler(commands=['user'])
def user_info_cmd(message):
    if not is_owner(message.from_user.id):
        return
    try:
        arg = message.text.split()[1].replace('@', '')
        users = load_data(DB_FILE)
        target_id = None

        if arg.isdigit() and arg in users:
            target_id = arg
        else:
            # Поиск по юзернейму в истории
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
    except Exception as e:
        bot.reply_to(message, "❌ Формат: `/user ID` или `/user @username`", parse_mode="Markdown")

@bot.message_handler(commands=['stats'])
def stats_cmd(message):
    if not is_owner(message.from_user.id):
        return
    users = load_data(DB_FILE)
    history = load_data(HISTORY_FILE)
    active_posts = load_data(POSTS_FILE)
    
    active_sub_count = 0
    now = time.time()
    for u_info in users.values():
        exp = u_info.get("expire", 0) if isinstance(u_info, dict) else u_info
        pts = u_info.get("posts", 0) if isinstance(u_info, dict) else 0
        if (exp > now) or pts > 0:
            active_sub_count += 1
            
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
    if not is_owner(message.from_user.id):
        return
    text_to_send = message.text.replace('/broadcast', '').strip()
    if not text_to_send:
        bot.reply_to(message, "❌ Напишите текст рассылки: `/broadcast Текст...`", parse_mode="Markdown")
        return

    users = load_data(DB_FILE)
    success = 0
    failed = 0

    bot.reply_to(message, f"📢 Запускаю рассылку на {len(users)} пользователей...")
    
    for u_id in list(users.keys()):
        try:
            bot.send_message(int(u_id), f"📢 **Объявление:**\n\n{text_to_send}", parse_mode="Markdown")
            success += 1
            time.sleep(0.05)
        except:
            failed += 1

    bot.send_message(message.chat.id, f"✅ **Рассылка завершена!**\nУспешно: {success} | Ошибок: {failed}", parse_mode="Markdown")

@bot.message_handler(commands=['list'])
def list_users(message):
    if not is_owner(message.from_user.id):
        return
    users = load_data(DB_FILE)
    if not users:
        bot.reply_to(message, "Список платных подписок пуст.")
        return
    
    text = "📋 **Активные подписки и посты:**\n\n"
    now = time.time()
    
    for u_id, u_info in list(users.items()):
        exp_time = u_info.get("expire", 0) if isinstance(u_info, dict) else u_info
        posts_left = u_info.get("posts", 0) if isinstance(u_info, dict) else 0
        
        left_days = round((exp_time - now) / 86400, 1)
        if left_days > 0 or posts_left > 0:
            user_tag = f"ID `{u_id}`"
            try:
                chat_info = bot.get_chat(int(u_id))
                if chat_info.username:
                    user_tag = f"@{chat_info.username} (`{u_id}`)"
            except:
                pass
                
            info_str = []
            if left_days > 0:
                info_str.append(f"{left_days} дн.")
            if posts_left > 0:
                info_str.append(f"{posts_left} постов")
                
            text += f"• {user_tag} — осталось: **{', '.join(info_str)}**\n"
        else:
            del users[u_id]
            save_data(DB_FILE, users)
            
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['uncd', 'uncooldown'])
def reset_cooldown_command(message):
    if not is_owner(message.from_user.id):
        return
    try:
        target_id = str(message.text.split()[1])
        reset_cooldown(target_id)
        bot.reply_to(message, f"⚡ Кулдаун для ID `{target_id}` успешно сброшен!", parse_mode="Markdown")
    except Exception:
        bot.reply_to(message, "❌ Формат: `/uncd ID`", parse_mode="Markdown")

@bot.message_handler(commands=['history'])
def show_history(message):
    if not is_owner(message.from_user.id):
        return
    history = load_data(HISTORY_FILE)
    if not history:
        bot.reply_to(message, "История постов пуста.")
        return
    text = "📜 **История последних публикаций:**\n\n"
    for item in history[-10:]:
        user_str = f"@{item['username']}" if item['username'] != "Без username" else f"ID {item['user_id']}"
        text += f"🕒 [{item['timestamp']}] {user_str}\n💬 {item['text'][:80]}...\n---\n"
    bot.reply_to(message, text)

# --- РУЧНОЕ ЗАКРЫТИЕ ПОСТА ---

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
        args = message.text.split()
        if len(args) > 1 and args[1].isdigit():
            target_post_id = args[1]

    if not target_post_id:
        user_posts = [p_id for p_id, info in posts_data.items() if info.get("user_id") == user_id]
        if user_posts:
            target_post_id = user_posts[-1]

    if not target_post_id:
        bot.reply_to(message, "❌ Активный пост не найден.\nДля старых постов укажи ID сообщения: `/close ID`", parse_mode="Markdown")
        return

    if target_post_id in posts_data:
        post_info = posts_data[target_post_id]
        if post_info["user_id"] != user_id and not is_owner(user_id):
            bot.reply_to(message, "⛔ Вы не можете закрыть чужой пост.")
            return

        created_at = post_info.get("created_at", time.time())
        time_passed = time.time() - created_at

        close_post_in_channel(int(target_post_id))

        del posts_data[target_post_id]
        save_data(POSTS_FILE, posts_data)

        if time_passed <= 60:
            reset_cooldown(user_id)
            bot.reply_to(message, "✅ **Пост успешно закрыт!**\n⚡ Кулдаун сброшен!")
        else:
            bot.reply_to(message, "✅ **Пост успешно закрыт!**")
            
    else:
        if is_owner(user_id):
            res = close_post_in_channel(int(target_post_id))
            if res:
                bot.reply_to(message, f"✅ Старый пост `{target_post_id}` успешно закрыт в канале!", parse_mode="Markdown")
            else:
                bot.reply_to(message, f"❌ Не удалось закрыть пост `{target_post_id}`. Проверь ID.", parse_mode="Markdown")
        else:
            bot.reply_to(message, "❌ Пост не найден в списке активных.")

# --- ОБРАБОТКА CALLBACK-КНОПОК ---

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    
    if call.data == "main_menu":
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="👋 Привет! Добро пожаловать в бот автопубликаций.\nВыберите нужный раздел ниже:",
            reply_markup=get_main_menu_keyboard(user_id)
        )

    elif call.data == "get_template":
        bot.answer_callback_query(call.id, "Шаблон готов к копированию!")
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"📋 **Нажми на текст ниже, чтобы скопировать его:**\n\n<code>{TEMPLATE_TEXT}</code>",
            parse_mode="HTML",
            reply_markup=get_back_keyboard()
        )

    elif call.data == "show_rules":
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=RULES_TEXT,
            parse_mode="Markdown",
            reply_markup=get_back_keyboard()
        )

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
            cd_str = format_time(cd) if cd > 0 else "Отсутствует (можно выкладывать пост)"
            
            prof_text = f"👤 **Ваш профиль:**\n\n"
            if left_days > 0:
                prof_text += f"• Подписка по дням: ~**{left_days} дн.**\n"
            if pts > 0:
                prof_text += f"• Разовые посты: **{pts} шт.**\n"
            prof_text += f"• Текущий кулдаун: **{cd_str}**"
        else:
            prof_text = "⛔ У вас нет активной подписки или доступных постов."

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=prof_text,
            parse_mode="Markdown",
            reply_markup=get_back_keyboard()
        )

    elif call.data == "open_admin_help":
        if is_owner(user_id):
            bot.answer_callback_query(call.id)
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=get_admin_help_text(),
                parse_mode="Markdown",
                reply_markup=get_back_keyboard()
            )

# --- ОБРАБОТКА СТАРТА ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id

    if is_user_active(user_id):
        bot.reply_to(
            message, 
            "👋 Привет! Добро пожаловать в бот автопубликаций.\nВыберите нужный раздел ниже:", 
            reply_markup=get_main_menu_keyboard(user_id)
        )
    else:
        bot.reply_to(
            message, 
            f"⛔ У вас нет доступа к публикации.\nВаш Telegram ID: `{user_id}`\n\nДля покупки доступа напишите администратору.", 
            parse_mode="Markdown"
        )

# --- ПУБЛИКАЦИЯ ПОСТОВ ---

@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'animation'])
def handle_post(message):
    if message.text and message.text.startswith('/'):
        return

    user_id = message.from_user.id
    
    # 1. Проверка подписки на канал
    if not check_channel_subscription(user_id):
        bot.reply_to(
            message, 
            f"❌ **Для использования бота вы должны быть подписаны на наш канал {CHANNEL_ID}!**\n Подпишитесь и отправьте пост снова.",
            parse_mode="Markdown"
        )
        return

    # 2. Проверка активности профиля
    if not is_user_active(user_id):
        bot.reply_to(message, f"⛔ Публикация отклонена. Подписка истекла или закончились посты.\nВаш ID: `{user_id}`", parse_mode="Markdown")
        return

    # 3. Проверка кулдауна
    cooldown_left = get_cooldown_left(user_id)
    if cooldown_left > 0:
        time_str = format_time(cooldown_left)
        bot.reply_to(message, f"⏳ **Кулдаун!**\nВы сможете опубликовать следующий пост через **{time_str}**.")
        return

    post_text = message.text or message.caption or ""

    # 4. Проверка шаблона и антискам
    is_valid, err_reason = validate_template_strict(post_text)
    if not is_valid:
        bot.reply_to(
            message, 
            f"❌ **Ошибка публикации!**\n\n"
            f"⚠️ *Причина:* {err_reason}\n\n"
            "👇 **Скопируйте чистый шаблон:**\n\n" + f"<code>{TEMPLATE_TEXT}</code>", 
            parse_mode="HTML"
        )
        return

    try:
        user = message.from_user
        username = user.username
        author_link = f"https://t.me/{username}" if username else f"tg://user?id={user_id}"

        published_msg = bot.copy_message(
            chat_id=CHANNEL_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="Перейти к выполнению 💬", url=author_link))
        
        bot.edit_message_reply_markup(
            chat_id=CHANNEL_ID,
            message_id=published_msg.message_id,
            reply_markup=markup
        )

        # Списание разового поста (если доступ поштучный)
        consume_post_credit(user_id)

        set_cooldown(user_id)
        save_to_history(user_id, username, post_text)
        
        confirm_msg = bot.reply_to(
            message, 
            "🚀 **Пост успешно выложен в канал!**\n\n"
            "📌 **Как закрыть пост:**\n"
            "Ответьте командой `/close` прямо на это сообщение.\n\n"
            "⏱ *Если вы закроете пост в течение 1 минуты — кулдаун сброситcя!*",
            parse_mode="Markdown"
        )

        posts_data = load_data(POSTS_FILE)
        posts_data[str(published_msg.message_id)] = {
            "user_id": user_id,
            "created_at": time.time(),
            "confirm_msg_id": confirm_msg.message_id,
            "original_text": post_text
        }
        save_data(POSTS_FILE, posts_data)

        # Отправка логов владельцу
        if not is_owner(user_id):
            user_tag = f"@{username}" if username else f"ID {user_id}"
            admin_log = f"📩 **Новый пост в канале!**\n👤 Автор: {user_tag}\n📝 Текст:\n{post_text}"
            for admin_id in OWNER_ID:
                try:
                    bot.send_message(admin_id, admin_log, parse_mode="Markdown")
                except:
                    pass

    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка публикации: {e}")

# --- ЗАПУСК ПОТОКОВ И ПОЛЛИНГА ---

threading.Thread(target=auto_close_checker, daemon=True).start()
threading.Thread(target=check_expiring_subscriptions_and_cooldowns, daemon=True).start()

if __name__ == '__main__':
    print("Бот запущен и готов к высокими нагрузкам...")
    while True:
        try:
            bot.polling(none_stop=True, timeout=30, long_polling_timeout=30, skip_pending=True)
        except Exception as e:
            print(f"Сетевой сбой: {e}. Переподключение через 5 секунд...")
            time.sleep(5)
