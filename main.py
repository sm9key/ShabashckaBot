import telebot
from telebot import types
from datetime import datetime, timedelta
import re
import logging
import json
import gc
import requests
import time

# Настройка логирования
logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

BOT_TOKEN = "7175241892:AAH_gsP6p0-pz7t7ENdcr4P7GtlkRJP24Z0"  # Токен для @Shabashcka_bot
bot = telebot.TeleBot(BOT_TOKEN)

# Путь к файлам для хранения данных
PROFILES_FILE = 'profiles.json'
REQUESTS_FILE = 'requests.json'
NOTIFICATIONS_FILE = 'notifications.json'
STATS_FILE = 'stats.json'

# Функции для сохранения и загрузки данных
def save_to_json(data, filename):
    try:
        with open(filename, 'w') as f:
            json.dump(data, f, default=str)
        logging.info(f"Saved data to {filename}")
    except Exception as e:
        logging.error(f"Failed to save data to {filename}: {str(e)}")

def load_from_json(filename, default_value):
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
        logging.info(f"Loaded data from {filename}")
        return data
    except Exception as e:
        logging.error(f"Failed to load data from {filename}: {str(e)}")
        return default_value

# Инициализация данных
profiles = load_from_json(PROFILES_FILE, {})
requests = load_from_json(REQUESTS_FILE, {})
notifications = load_from_json(NOTIFICATIONS_FILE, {})
stats = load_from_json(STATS_FILE, {})

for user_id, req in requests.items():
    req['expiry'] = datetime.fromisoformat(req['expiry'])
    req['created'] = datetime.fromisoformat(req['created'])

states = {}

menu_configs = {
    "main": ["Найти", "Редактировать профиль", "Создать заявка", "Посмотреть заявки", "Мой профиль", "Выбрать город", "Частые вопросы", "О боте", "Обратная связь", "Премиум", "Помощь"],
    "city": ["Москва", "Санкт-Петербург", "Екатеринбург", "Другое", "Вернуться в меню"],
    "placement": ["Долгий поиск", "Одноразовая заявка", "Вернуться в меню"],
    "back": ["Вернуться в меню"]
}

def get_menu(menu_type):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    buttons = menu_configs.get(menu_type, [])
    for btn in buttons:
        markup.add(types.KeyboardButton(btn))
    return markup

def moderate_text(text):
    phone_pattern = r'(\+?\d{1,2}\s?)?(\d{3}\s?\d{3}\s?\d{2}\s?\d{2}|\d{10,11})'
    return re.sub(phone_pattern, "[Скрытый номер]", text)

def parse_location(text):
    return text if text in ["Москва", "Санкт-Петербург", "Екатеринбург", "Другое"] else None

def start_profile_creation(message, state):
    user_id = message.from_user.id
    state.role = None
    state.data = {}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("Соискатель", "Работодатель")
    bot.reply_to(message, "Похоже, у вас ещё нет профиля. Давайте создадим его!\nВыбери роль:", reply_markup=markup)

class UserState:
    def __init__(self, user_id):
        self.user_id = user_id
        self.role = None
        self.data = {}

    def next_step(self, message):
        text = message.text if hasattr(message, 'text') else None

        if text == "Вернуться в меню":
            bot.reply_to(message, "Вы вернулись в главное меню.", reply_markup=get_menu("main"))
            return False

        if text in ["/start", "Соискатель", "Работодатель"] and not self.data.get("description"):
            self.role = None
            self.data = {}

        if not self.role and text in ["Соискатель", "Работодатель"]:
            self.role = "seeker" if text == "Соискатель" else "employer"
            example = "Могу работать грузчиком, 1500 руб/день" if self.role == "seeker" else "Нужны грузчики на завтра, 1500 руб/день"
            bot.reply_to(message, f"Роль '{self.role}' выбрана. Пример: '{example}'\nВведите описание:", reply_markup=get_menu("back"))
            bot.register_next_step_handler(message, self.next_step)
            return True

        elif self.data.get("description") is None:
            self.data["description"] = moderate_text(text)
            bot.reply_to(message, "Выберите город:", reply_markup=get_menu("city"))
            bot.register_next_step_handler(message, self.next_step)
            return True

        elif self.data.get("city") is None:
            if text == "Другое" and message.location:
                bot.reply_to(message, "Геолокация получена, но город определяется вручную. Введите название города:", reply_markup=get_menu("back"))
                bot.register_next_step_handler(message, self.process_custom_city)
            elif text == "Другое":
                bot.reply_to(message, "Введите название города вручную:", reply_markup=get_menu("back"))
                bot.register_next_step_handler(message, self.process_custom_city)
            else:
                self.data["city"] = text
                bot.reply_to(message, "Выберите действие:", reply_markup=get_menu("placement"))
                bot.register_next_step_handler(message, self.process_placement)
            return True

        return False

    def process_custom_city(self, message):
        self.data["city"] = message.text
        bot.reply_to(message, "Выберите действие:", reply_markup=get_menu("placement"))
        bot.register_next_step_handler(message, self.process_placement)

    def process_placement(self, message):
        if message.text == "Вернуться в меню":
            bot.reply_to(message, "Вы вернулись в главное меню.", reply_markup=get_menu("main"))
            return
        profiles[self.user_id] = {
            "role": self.role,
            "data": self.data,
            "last_updated": datetime.now().isoformat()
        }
        save_to_json(profiles, PROFILES_FILE)
        if message.text == "Долгий поиск":
            bot.reply_to(message, "Профиль сохранён для долгого поиска!", reply_markup=get_menu("main"))
        elif message.text == "Одноразовая заявка":
            self.save_request(message)
            bot.reply_to(message, f"Заявка сохранена (удалится через 24 часа): {self.data['description']}", reply_markup=get_menu("main"))

    def save_request(self, message):
        user_stats = stats.setdefault(self.user_id, {
            "total_requests": 0,
            "searches": 0,
            "profile_views": 0,
            "weekly_requests": 0,
            "last_reset": datetime.now().isoformat()
        })
        current_time = datetime.now()
        last_reset = datetime.fromisoformat(user_stats["last_reset"])
        if (current_time - last_reset).days >= 7:
            user_stats["weekly_requests"] = 0
            user_stats["last_reset"] = current_time.isoformat()
        if user_stats["weekly_requests"] >= 3:
            bot.reply_to(message, f"Ты достиг лимита заявок (3 в неделю). Подожди до следующей недели или напиши в поддержку: @shbsupport", reply_markup=get_menu("main"))
            return
        user_stats["weekly_requests"] += 1
        user_stats["total_requests"] += 1
        save_to_json(stats, STATS_FILE)
        requests[self.user_id] = {
            "role": self.role,
            "request": self.data["description"],
            "expiry": datetime.now() + timedelta(hours=24),
            "user_id": self.user_id,
            "location": self.data["city"],
            "created": datetime.now()
        }
        save_to_json(requests, REQUESTS_FILE)
        for user_id, profile in profiles.items():
            if user_id != self.user_id and profile.get("data", {}).get("city") == self.data["city"] and profile.get("role") != self.role:
                bot.send_message(user_id, f"📢 Новая заявка в твоём городе: {self.data['description']}")

def clean_old_profiles():
    current_time = datetime.now()
    for user_id, profile in list(profiles.items()):
        last_updated = profile.get("last_updated", datetime.now().isoformat())
        last_updated = datetime.fromisoformat(last_updated)
        if (current_time - last_updated).days > 30:
            del profiles[user_id]
            logging.info(f"Removed inactive profile for user {user_id}")
    save_to_json(profiles, PROFILES_FILE)

def manage_requests():
    current_time = datetime.now()
    for uid, req in list(requests.items()):
        if current_time > req["expiry"]:
            del requests[uid]
            save_to_json(requests, REQUESTS_FILE)
            continue
        time_left = (req["expiry"] - current_time).total_seconds() / 3600
        if time_left <= 1 and uid not in notifications.get("expiring", {}):
            markup = types.ReplyKeyboardMarkup()
            markup.add("Удалить", "Оставить")
            bot.send_message(uid, f"Ваша заявка '{req['request']}' истекает через 1 час!", reply_markup=markup)
            notifications.setdefault("expiring", {})[uid] = True
            save_to_json(notifications, NOTIFICATIONS_FILE)
            bot.register_next_step_handler_by_chat_id(uid, process_request_expiry, uid)
    clean_old_profiles()
    gc.collect()

def process_request_expiry(message, request_id):
    if message.text == "Удалить":
        del requests[request_id]
        save_to_json(requests, REQUESTS_FILE)
        bot.send_message(request_id, "Заявка удалена.", reply_markup=get_menu("main"))
    elif message.text == "Оставить":
        bot.send_message(request_id, "Заявка осталась активна.", reply_markup=get_menu("main"))
    if "expiring" in notifications and request_id in notifications["expiring"]:
        del notifications["expiring"][request_id]
        save_to_json(notifications, NOTIFICATIONS_FILE)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    stats.setdefault(user_id, {
        "total_requests": 0,
        "searches": 0,
        "profile_views": 0,
        "weekly_requests": 0,
        "last_reset": datetime.now().isoformat()
    })
    save_to_json(stats, STATS_FILE)
    states[user_id] = UserState(user_id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("Соискатель", "Работодатель")
    welcome_text = (
        "👋 Привет! Я бот для поиска работы и работников.\n"
        "Выбери роль:\n"
        "- **Соискатель**: если ты ищешь работу.\n"
        "- **Работодатель**: если тебе нужны сотрудники.\n\n"
        "После выбора роли ты сможешь создать профиль, искать заявки или размещать свои."
    )
    bot.reply_to(message, welcome_text, reply_markup=markup)
    logging.info(f"User {user_id} started the bot")

@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = (
        "📋 **Инструкции**:\n"
        "- Выбери роль и заполни профиль.\n"
        "- Используй 'Найти' для поиска.\n"
        "- Для создания заявки выбери 'Создать заявка'.\n\n"
        "Если что-то не работает, используй 'Частые вопросы' в меню."
    )
    bot.reply_to(message, help_text, reply_markup=get_menu("main"))
    logging.info(f"User {message.from_user.id} requested help")

def handle_feedback(message):
    user_id = message.from_user.id
    feedback = message.text
    if feedback == "Вернуться в меню":
        bot.reply_to(message, "Вы вернулись в главное меню.", reply_markup=get_menu("main"))
        return
    logging.info(f"Feedback from user {user_id}: {feedback}")
    bot.reply_to(message, "Спасибо за обратную связь! Я передал её создателю (@shbsupport).", reply_markup=get_menu("main"))
    bot.send_message(7594987801, f"📢 Обратная связь от {user_id}:\n{feedback}")

@bot.message_handler(content_types=['text', 'location'])
def handle_input(message):
    try:
        user_id = message.from_user.id
        state = states.get(user_id, UserState(user_id))

        if message.text in menu_configs["main"]:
            if message.text == "Выбрать город":
                bot.reply_to(message, "Выберите город:", reply_markup=get_menu("city"))
            elif message.text == "Создать заявка":
                logging.info(f"User {user_id} used 'Создать заявка'")
                state.data = {}
                example = "Могу работать грузчиком, 1500 руб/день" if state.role == "seeker" else "Нужны грузчики на завтра, 1500 руб/день"
                bot.reply_to(message, f"Пример: '{example}'\nВведите описание:", reply_markup=get_menu("back"))
            elif message.text == "Редактировать профиль":
                logging.info(f"User {user_id} used 'Редактировать профиль'")
                if user_id in profiles:
                    state.data = profiles[user_id]["data"]
                    example = "Могу работать грузчиком, 1500 руб/день" if state.role == "seeker" else "Нужны грузчики на завтра, 1500 руб/день"
                    bot.reply_to(message, f"Введите новое описание (пример: '{example}'):", reply_markup=get_menu("back"))
                else:
                    start_profile_creation(message, state)
            elif message.text == "Найти":
                logging.info(f"User {user_id} used 'Найти'")
                stats[user_id]["searches"] += 1
                save_to_json(stats, STATS_FILE)
                if user_id in profiles:
                    find_match(message)
                else:
                    start_profile_creation(message, state)
            elif message.text == "Посмотреть заявки":
                logging.info(f"User {user_id} used 'Посмотреть заявки'")
                show_requests(message)
            elif message.text == "Мой профиль":
                logging.info(f"User {user_id} used 'Мой профиль'")
                stats[user_id]["profile_views"] += 1
                save_to_json(stats, STATS_FILE)
                if user_id in profiles:
                    bot.reply_to(message, format_profile(user_id), reply_markup=get_menu("main"))
                else:
                    start_profile_creation(message, state)
            elif message.text == "Частые вопросы":
                faq_text = (
                    "❓ **Частые вопросы и решения**:\n\n"
                    "1. **Почему не работает 'Мой профиль'?**\n"
                    "   - Вы ещё не создали профиль. Бот автоматически начнёт процесс создания, если выберешь 'Мой профиль'.\n\n"
                    "2. **Почему 'Найти' не показывает результаты?**\n"
                    "   - Убедись, что твой профиль создан и город указан. Также может не быть подходящих профилей в твоём городе.\n\n"
                    "3. **Как вернуться в главное меню?**\n"
                    "   - Нажми 'Вернуться в меню' или введи /start, чтобы начать заново.\n\n"
                    "4. **Что делать, если я не вижу кнопок?**\n"
                    "   - Попробуй перезапустить бота командой /start или проверь, не скрыта ли клавиатура в Telegram.\n\n"
                    "Если проблема не решилась, напиши в поддержку: @shbsupport"
                )
                bot.reply_to(message, faq_text, reply_markup=get_menu("main"))
            elif message.text == "О боте":
                about_text = (
                    "🤖 Я @Shabashcka_bot — помощник для поиска работы и работников.\n"
                    "Сейчас я на стадии альфа-теста, поэтому буду рад твоей обратной связи!\n"
                    "Если у тебя есть идеи или ты нашёл баг, напиши в поддержку: @shbsupport"
                )
                bot.reply_to(message, about_text, reply_markup=get_menu("main"))
            elif message.text == "Обратная связь":
                bot.reply_to(message, "Напиши свои предложения или сообщай о багах. Я передам это в поддержку (@shbsupport)!", reply_markup=get_menu("back"))
                bot.register_next_step_handler(message, handle_feedback)
            elif message.text == "Премиум":
                bot.reply_to(message, "🔒 Премиум-функции пока в разработке. Скоро ты сможешь:\n- Создавать больше заявок\n- Получать приоритет в поиске\nСледи за обновлениями!", reply_markup=get_menu("main"))
            elif message.text == "Помощь":
                send_help(message)
            return

        if state.next_step(message):
            states[user_id] = state
    except Exception as e:
        logging.error(f"Error in handle_input for user {user_id}: {str(e)}")
        bot.reply_to(message, f"Произошла ошибка. Попробуй снова или напиши в поддержку: @shbsupport", reply_markup=get_menu("main"))

def format_profile(user_id):
    profile = profiles.get(user_id, {})
    role = "Соискатель" if profile.get('role', '') == "seeker" else "Работодатель"
    return (
        f"🆔 ID: {user_id}\n"
        f"👤 Роль: {role}\n"
        f"📝 Описание: {profile.get('data', {}).get('description', '')}\n"
        f"🌆 Город: {profile.get('data', {}).get('city', '')}"
    )

def find_match(message):
    user_id = message.from_user.id
    user_city = profiles.get(user_id, {}).get("data", {}).get("city")
    if not user_city:
        bot.reply_to(message, "Установите город. Используй 'Выбрать город' в меню.", reply_markup=get_menu("main"))
        return
    user_description = profiles.get(user_id, {}).get("data", {}).get("description", "").lower()
    matches = [
        p for p_id, p in profiles.items()
        if p_id != user_id
        and p.get("data", {}).get("city") == user_city
        and p.get("role") != profiles[user_id]["role"]
        and any(keyword in p.get("data", {}).get("description", "").lower() for keyword in user_description.split())
    ]
    if matches[:2]:
        for match in matches[:2]:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Написать", url=f"tg://user?id={match['user_id']}"))
            bot.reply_to(message, format_profile(match["user_id"]), reply_markup=markup)
    else:
        bot.reply_to(message, "Совпадений не найдено. Попробуй изменить город или создай заявку.", reply_markup=get_menu("main"))

def show_requests(message):
    user_id = message.from_user.id
    user_city = profiles.get(user_id, {}).get("data", {}).get("city") if user_id in profiles else None
    if not user_city:
        bot.reply_to(message, "Установите город. Используй 'Выбрать город' в меню.", reply_markup=get_menu("main"))
        return
    active_requests = [req for req in requests.values() if req.get("location") == user_city]
    if active_requests[:2]:
        for req in active_requests[:2]:
            bot.reply_to(message, f"Заявка: {req['request']} (ID: {req['user_id']})", reply_markup=get_menu("main"))
    else:
        bot.reply_to(message, "Активных заявок нет. Создай заявку или попробуй другой город.", reply_markup=get_menu("main"))

if __name__ == "__main__":
    logging.info(f"Bot started. Current server time: {datetime.now()}")
    from background import keep_alive
    keep_alive()  # Запускаем Flask-сервер
    while True:
        try:
            logging.info("Starting bot polling...")
            bot.polling(none_stop=True, interval=1)
        except Exception as e:
            logging.error(f"Polling error: {str(e)}")
            time.sleep(5)  # Ждём 5 секунд перед перезапуском
