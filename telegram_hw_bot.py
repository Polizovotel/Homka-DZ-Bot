import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from telegram.constants import ChatAction
import json
import datetime
import logging
import asyncio
import random
import sys
import os
import httpx  # Импорт для работы с Groq AI
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# Загружаем переменные окружения из файла .env (создайте его на основе .env.example)
load_dotenv()

# --- КОНСТАНТЫ И НАСТРОЙКИ ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DATA_FILE = "data.json"

if not TOKEN:
    raise RuntimeError(
        "Не задан TELEGRAM_BOT_TOKEN. Создайте файл .env на основе .env.example и заполните его."
    )
if not OWNER_ID:
    raise RuntimeError(
        "Не задан OWNER_ID. Создайте файл .env на основе .env.example и заполните его."
    )

# Настройки Groq API (https://console.groq.com)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_AI_MODEL = os.getenv("GROQ_AI_MODEL", "llama-3.1-8b-instant")

# Типы учебных заведений
INSTITUTION_TYPES = ["Школа", "Гимназия", "Лицей", "Колледж", "Университет"]

# Полный список реакций
ALL_REACTIONS = [
    "👍", "👎", "❤", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱",
    "🤬", "😢", "🎉", "🤩", "🤮", "💩", "🙏", "👌", "🕊", "🤡",
    "🥱", "🥴", "😍", "🐳", "❤‍🔥", "🌚", "🌭", "💯", "🤣", "⚡",
    "🍌", "🏆", "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕", "😈",
    "😴", "😭", "🤓", "👻", "👨‍💻", "👀", "🎃", "🙈", "😇", "😨",
    "🤝", "✍", "🤗", "🫡", "🎅", "🎄", "☃", "💅", "🤪", "🗿",
    "🆒", "💘", "🙉", "🦄", "😘", "💊", "🙊", "😎", "👾", "🤷" + "‍♂️",
                                                 "🤷" + "‍♀️", "😡"
]

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def escape_md(text: str) -> str:
    if not text:
        return ""
    return text.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")


def get_hw_text(hw_entry: Dict) -> str:
    return hw_entry.get("text", "")


def get_hw_photos(hw_entry: Dict) -> List[str]:
    return hw_entry.get("photos", [])


def get_next_lesson_date(subject: str, schedule: Dict[str, List[str]], start_date: datetime.date) -> Optional[
    datetime.date]:
    """Находит дату следующего урока по расписанию в пределах 3 недель."""
    for i in range(1, 22):  # Ищем в пределах 3 недель (21 день)
        future_date = start_date + datetime.timedelta(days=i)
        day_name_en = future_date.strftime("%A")
        if subject in schedule.get(day_name_en, []):
            return future_date
    return None


async def cleanup_hw_photos(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """
    Удаляет отправленные фотографии ДЗ из чата, чтобы не засорять историю.
    Вызывается ИСКЛЮЧИТЕЛЬНО при осознанном выходе назад в меню по кнопке.
    """
    if 'photo_msgs' in context.user_data:
        logger.info(f"Запуск очистки временных медиа-сообщений для чата {chat_id}")
        for msg_id in context.user_data['photo_msgs']:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                # Игнорируем ошибки (например, если сообщение уже удалено пользователем)
                logger.debug(f"Не удалось удалить временное сообщение {msg_id}: {e}")
        context.user_data['photo_msgs'] = []  # Очищаем список после удаления


# --- ФУНКЦИИ РАБОТЫ С ДАННЫМИ ---
def load_data() -> Dict[str, Any]:
    default_subjects = ["Математика", "Русский язык", "История"]

    default_data = {
        "admins": [OWNER_ID],
        "blacklist": [],
        "forward_list": [],
        "homework": {},
        "schedule": {},
        "subjects": default_subjects,
        "users": {},
        "reaction_groups": {
            "default": ["👍", "❤", "🔥"]
        },
        "materials": {}
    }

    try:
        if not os.path.exists(DATA_FILE):
            logger.info(f"Файл {DATA_FILE} отсутствует. Создаю с дефолтными значениями.")
            return default_data

        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

            if "admins" not in data: data["admins"] = []
            if "blacklist" not in data: data["blacklist"] = []
            if "forward_list" not in data: data["forward_list"] = []
            if "homework" not in data: data["homework"] = {}
            if "schedule" not in data: data["schedule"] = {}
            if "subjects" not in data: data["subjects"] = default_subjects
            if "users" not in data: data["users"] = {}
            if "materials" not in data: data["materials"] = {}

            if "reaction_groups" not in data:
                data["reaction_groups"] = {"default": ["👍"]}

            if OWNER_ID not in data["admins"]:
                data["admins"].append(OWNER_ID)

            return data
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Ошибка при чтении {DATA_FILE}: {e}. Создаю новый.")
        return default_data


def save_data(data: Dict[str, Any]):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            if isinstance(data.get("subjects"), list):
                data["subjects"].sort()
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Ошибка при сохранении данных в {DATA_FILE}: {e}")


def update_user_activity(user_id: int, data: Dict[str, Any]):
    uid = str(user_id)
    if uid in data["users"]:
        data["users"][uid]["last_active"] = datetime.datetime.now().isoformat()
        if "reaction_group" not in data["users"][uid]:
            data["users"][uid]["reaction_group"] = "default"


def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def is_admin(user_id: int, data: Dict[str, Any]) -> bool:
    return user_id in data.get("admins", []) or user_id == OWNER_ID


def is_blacklisted(user_id: int, data: Dict[str, Any]) -> bool:
    return user_id in data.get("blacklist", [])


def get_user_class_key(user_id: int, data: Dict[str, Any]) -> Optional[str]:
    """Возвращает уникальный ключ для БД: 'Тип Номер : Класс'."""
    user = data["users"].get(str(user_id), {})
    inst_type = user.get("inst_type")
    inst_num = user.get("inst_num")
    class_name = user.get("class_name")

    if inst_type and inst_num and class_name:
        return f"{inst_type} {inst_num} : {class_name}"
    return None


def get_user_display_info(user_id: int, data: Dict[str, Any]) -> str:
    """Возвращает красивое описание класса."""
    user = data["users"].get(str(user_id), {})
    inst_type = user.get("inst_type", "Школа")
    inst_num = user.get("inst_num", "?")
    class_name = user.get("class_name", "?")
    return f"{inst_type} №{inst_num}, Класс {class_name}"


# --- ИНТЕГРАЦИЯ GROQ AI ---
async def ask_groq_ai(prompt: str) -> str:
    """Отправляет запрос к Groq API (OpenAI-совместимый эндпоинт)."""
    if not GROQ_API_KEY:
        return "⚠️ Модуль ИИ не настроен администратором. (Отсутствует GROQ_API_KEY)."

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    # Системные инструкции для адаптации ответов под школьного ИИ-помощника
    # Добавлен строгий запрет на английский язык и нежелательные переводы
    payload = {
        "model": GROQ_AI_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты — вежливый, мудрый и дружелюбный школьный ИИ-помощник. Твоя задача — помогать ученикам "
                    "в учёбе, объяснять сложные темы доступным и ясным языком, давать структурированные "
                    "и понятные ответы на русском языке. Ответы должны быть развивающими, понятными и полностью безопасными. "
                    "СТРОГОЕ ПРАВИЛО: Пиши ИСКЛЮЧИТЕЛЬНО на русском языке. Не используй английские слова, фразы "
                    "или предложения, если тебя об этом прямо не попросил пользователь. Все термины переводи на русский "
                    "или подробно поясняй по-русски."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "max_tokens": 1500  # Явное увеличение лимита токенов, чтобы ответ не обрезался на середине предложения
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=35.0)
            if response.status_code == 200:
                res_json = response.json()
                choices = res_json.get("choices", [])
                if choices:
                    return choices[0]["message"]["content"]
                return "❌ Groq вернул пустой ответ."
            elif response.status_code == 429:
                return "⏳ Превышен лимит запросов к ИИ. Попробуйте немного позже."
            else:
                err_body = response.text[:300]
                logger.error(f"Groq API HTTP {response.status_code}: {err_body}")
                return f"❌ Сервер Groq вернул ошибку: HTTP {response.status_code}"
    except Exception as e:
        logger.error(f"Ошибка при запросе к Groq AI: {e}")
        return "❌ Не удалось связаться со службой ИИ. Пожалуйста, попробуйте позже."


# --- КЛАВИАТУРЫ ---
def get_week_start(date_obj: datetime.date) -> datetime.date:
    return date_obj - datetime.timedelta(days=date_obj.weekday())


def get_institution_type_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    for t in INSTITUTION_TYPES:
        row.append(InlineKeyboardButton(t, callback_data=f"reg_type:{t}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)


def get_reg_grade_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    for i in range(1, 12):
        row.append(InlineKeyboardButton(str(i), callback_data=f"reg_grade:{i}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)


def get_reg_letter_keyboard() -> InlineKeyboardMarkup:
    letters = "АБВГДЕЖЗИКЛМНОПРСТУФ"
    keyboard = []
    row = []
    for char in letters:
        row.append(InlineKeyboardButton(char, callback_data=f"reg_letter:{char}"))
        if len(row) == 5:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)


def get_menu_keyboard(user_id: int, data: Dict[str, Any]) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("👀 Посмотреть ДЗ", callback_data="view_hw"),
            InlineKeyboardButton("🗄️ Архив ДЗ", callback_data="view_hw_past")
        ],
        [
            InlineKeyboardButton("📚 Полезные материалы", callback_data="user_materials_menu"),
            InlineKeyboardButton("🎮 Игра / Профиль", callback_data="game_menu")
        ]
    ]

    if is_admin(user_id, data):
        admin_row = [
            InlineKeyboardButton("➕ Добавить ДЗ", callback_data="admin_addhw"),
            InlineKeyboardButton("✍️ Редактировать", callback_data="admin_edithw"),
        ]
        keyboard.append(admin_row)

        admin_row_2 = [
            InlineKeyboardButton("❌ Удалить ДЗ", callback_data="admin_removehw"),
            InlineKeyboardButton("➡️ Перенести ДЗ", callback_data="admin_postponehw"),
        ]
        keyboard.append(admin_row_2)

        keyboard.append([InlineKeyboardButton("🛠️ Админ-панель", callback_data="admin_manage_hub")])

    return InlineKeyboardMarkup(keyboard)


def get_game_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("💰 Забрать ежедневную награду", callback_data="game_claim")],
        [InlineKeyboardButton("🏆 Топ игроков", callback_data="game_leaderboard")],
        [InlineKeyboardButton("🔄 Сменить школу/класс", callback_data="reg_start")],
        [InlineKeyboardButton("⬅️ Назад в меню", callback_data="back_to_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_day_selection_keyboard(monday_start: datetime.date, action_name: str,
                               class_schedule: Dict[str, List[str]] = None,
                               highlight_subject: str = None,
                               next_lesson_date: datetime.date = None) -> InlineKeyboardMarkup:
    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    today = datetime.date.today()
    if class_schedule is None:
        class_schedule = {}

    keyboard_rows = []

    if next_lesson_date:
        btn_text = f"🔜 На след. урок ({next_lesson_date.strftime('%d.%m')})"
        callback = f"select_day:{action_name}:{next_lesson_date.strftime('%Y-%m-%d')}"
        keyboard_rows.append([InlineKeyboardButton(btn_text, callback_data=callback)])

    current_row = []

    for i in range(7):
        date = monday_start + datetime.timedelta(days=i)
        day_name_ru = day_names[i]
        day_name_en = date.strftime("%A")

        marker = ""

        if highlight_subject:
            subjects_on_day = class_schedule.get(day_name_en, [])
            if highlight_subject in subjects_on_day:
                marker = "📌"
        else:
            if class_schedule.get(day_name_en):
                marker = "📝"

        display_text = f"{day_name_ru} {marker}".strip()

        if date == today:
            display_text = f"📅 {display_text}"

        callback_data = f"select_day:{action_name}:{date.strftime('%Y-%m-%d')}"
        current_row.append(InlineKeyboardButton(display_text, callback_data=callback_data))

        if len(current_row) == 4:
            keyboard_rows.append(current_row)
            current_row = []

    if current_row:
        keyboard_rows.append(current_row)

    prev_week_monday = monday_start - datetime.timedelta(weeks=1)
    next_week_monday = monday_start + datetime.timedelta(weeks=1)

    prev_week_display = f"⬅️ {prev_week_monday.strftime('%d.%m')}"
    next_week_display = f"{next_week_monday.strftime('%d.%m')} ➡️"
    current_week_display = f"Неделя с {monday_start.strftime('%d.%m')}"

    navigation_row = [
        InlineKeyboardButton(prev_week_display,
                             callback_data=f"navigate_week:{action_name}:{prev_week_monday.strftime('%Y-%m-%d')}"),
        InlineKeyboardButton(current_week_display, callback_data="ignore"),
        InlineKeyboardButton(next_week_display,
                             callback_data=f"navigate_week:{action_name}:{next_week_monday.strftime('%Y-%m-%d')}")
    ]
    back_row = [InlineKeyboardButton("🗓️ Назад в меню", callback_data="back_to_menu")]

    final_keyboard = keyboard_rows + [navigation_row, back_row]
    return InlineKeyboardMarkup(final_keyboard)


def get_simple_subject_list_keyboard(subjects: List[str], action: str) -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    for subject in subjects:
        callback_data = f"{action}:{subject}"
        row.append(InlineKeyboardButton(subject, callback_data=callback_data))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_homework_selection_keyboard(date_str: str, date_hw: Dict[str, Any], action: str) -> InlineKeyboardMarkup:
    keyboard = []

    if not date_hw:
        keyboard.append([InlineKeyboardButton("⚠️ На этот день заданий нет", callback_data="ignore")])

    elif action in ('edit', 'remove', 'postpone'):
        for subject in sorted(date_hw.keys()):
            entry = date_hw[subject]
            text_preview = get_hw_text(entry)
            task_preview = text_preview[:20].replace('\n', ' ') + '...' if len(
                text_preview) > 20 else text_preview.replace('\n', ' ')

            if not task_preview and get_hw_photos(entry):
                task_preview = "[Фото]"

            icon = "✏️" if action == "edit" else "🗑️" if action == "remove" else "➡️"
            button_text = f"{icon} {subject} - {task_preview}"
            callback_data = f"select_hw_for_{action}:{date_str}:{subject}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

        if action == 'remove':
            keyboard.append(
                [InlineKeyboardButton("💥 Удалить все ДЗ на дату", callback_data=f"confirm_remove_all:{date_str}")])
        elif action == 'postpone':
            keyboard.append(
                [InlineKeyboardButton("📦 Сдвинуть ВСЕ расписание", callback_data=f"confirm_postpone_all:{date_str}")])

    if action == 'edit':
        keyboard.append([InlineKeyboardButton("❌ Отмена / Выбрать другую дату", callback_data="admin_edithw")])
    elif action == 'remove':
        keyboard.append([InlineKeyboardButton("❌ Отмена / Выбрать другую дату", callback_data="admin_removehw")])
    elif action == 'postpone':
        if date_hw:  # Показываем кнопку авто-переноса только если есть что переносить
            keyboard.append(
                [InlineKeyboardButton("🚫 Отменить день (авто-перенос ДЗ)", callback_data=f"cancel_day:{date_str}")])
        keyboard.append([InlineKeyboardButton("❌ Отмена / Выбрать другую дату", callback_data="admin_postponehw")])
    else:
        keyboard.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data="back_to_menu")])

    return InlineKeyboardMarkup(keyboard)


def get_subject_management_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("➕ Добавить Предмет", callback_data="admin_subject_add_prompt"),
            InlineKeyboardButton("➖ Удалить Предмет", callback_data="admin_subject_remove_prompt")
        ],
        [
            InlineKeyboardButton("👀 Посмотреть список", callback_data="admin_subject_view")
        ],
        [
            InlineKeyboardButton("⬅️ Назад в Управление", callback_data="admin_manage_hub")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_hub_keyboard(user_id: int, data: Dict[str, Any]) -> InlineKeyboardMarkup:
    keyboard = []

    if is_owner(user_id):
        keyboard.append([
            InlineKeyboardButton("🔑 Админы", callback_data="admin_manage_users"),
            InlineKeyboardButton("⛔ Чёрный список", callback_data="admin_blacklist_menu")
        ])
        keyboard.append([
            InlineKeyboardButton("🎭 Реакции", callback_data="admin_reactions_menu"),
            InlineKeyboardButton("📨 Пересылка", callback_data="admin_forward_menu")
        ])
        keyboard.append([
            InlineKeyboardButton("✉️ Написать пользователю", callback_data="admin_dm_menu")
        ])

    keyboard.append([
        InlineKeyboardButton("📚 Предметы", callback_data="admin_manage_subjects"),
        InlineKeyboardButton("📅 Расписание", callback_data="admin_schedule_menu")
    ])

    if is_admin(user_id, data):
        keyboard.append([
            InlineKeyboardButton("📚 Файлы и памятки", callback_data="admin_materials_hub")
        ])
        keyboard.append([
            InlineKeyboardButton("🗑️ Удалить старое ДЗ", callback_data="admin_cleanup_prompt")
        ])
        keyboard.append([InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast_prompt")])

    if is_owner(user_id):
        keyboard.append([InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")])

    keyboard.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data="back_to_menu")])

    return InlineKeyboardMarkup(keyboard)


def get_blacklist_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("➕ Забанить (ID)", callback_data="admin_blacklist_add_prompt"),
            InlineKeyboardButton("➖ Разбанить (ID)", callback_data="admin_blacklist_remove_prompt")
        ],
        [
            InlineKeyboardButton("👀 Список заблокированных", callback_data="admin_blacklist_view")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="admin_manage_hub")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_forward_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("➕ Добавить (ID)", callback_data="admin_forward_add_prompt"),
            InlineKeyboardButton("➖ Удалить (ID)", callback_data="admin_forward_remove_prompt")
        ],
        [
            InlineKeyboardButton("👀 Список", callback_data="admin_forward_view")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="admin_manage_hub")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_users_list_keyboard(data: Dict[str, Any], page: int = 0) -> InlineKeyboardMarkup:
    """Список пользователей с постраничной навигацией для выбора получателя."""
    users_per_page = 8
    user_items = sorted(
        data.get("users", {}).items(),
        key=lambda item: (item[1].get("first_name") or "").lower()
    )
    total_pages = max(1, (len(user_items) + users_per_page - 1) // users_per_page)
    page = max(0, min(page, total_pages - 1))

    keyboard = []
    for uid, udata in user_items[page * users_per_page:(page + 1) * users_per_page]:
        name = udata.get("first_name") or "Без имени"
        username = udata.get("username")
        label = f"{name} (@{username})" if username else f"{name} (ID {uid})"
        if len(label) > 55:
            label = label[:52] + "..."
        keyboard.append([InlineKeyboardButton(label, callback_data=f"dm_user:{uid}")])

    if not user_items:
        keyboard.append([InlineKeyboardButton("Пользователей нет", callback_data="ignore")])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"dm_page:{page - 1}"))
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"dm_page:{page + 1}"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_manage_hub")])
    return InlineKeyboardMarkup(keyboard)


def get_reaction_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("➕ Группа", callback_data="admin_react_create"),
            InlineKeyboardButton("➖ Группа", callback_data="admin_react_delete")
        ],
        [
            InlineKeyboardButton("✏️ Изменить эмодзи", callback_data="admin_react_edit"),
            InlineKeyboardButton("👤 Назначить группу", callback_data="admin_react_assign")
        ],
        [
            InlineKeyboardButton("👀 Список групп", callback_data="admin_react_view")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="admin_manage_hub")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_reaction_groups_list_keyboard(data: Dict[str, Any], action: str) -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    for group_name in data.get("reaction_groups", {}):
        callback_data = f"{action}:{group_name}"
        row.append(InlineKeyboardButton(group_name, callback_data=callback_data))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="admin_reactions_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_emoji_selection_keyboard(group_name: str, current_emojis: List[str], page: int = 0) -> InlineKeyboardMarkup:
    items_per_page = 20
    start_index = page * items_per_page
    end_index = start_index + items_per_page
    page_emojis = ALL_REACTIONS[start_index:end_index]

    keyboard = []
    row = []
    for emo in page_emojis:
        text = f"✅ {emo}" if emo in current_emojis else emo
        callback_data = f"react_toggle:{group_name}:{page}:{emo}"
        row.append(InlineKeyboardButton(text, callback_data=callback_data))

        if len(row) == 4:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"react_page:{group_name}:{page - 1}"))

    nav_row.append(InlineKeyboardButton("🔙 Готово", callback_data="admin_reactions_menu"))

    if end_index < len(ALL_REACTIONS):
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"react_page:{group_name}:{page + 1}"))

    keyboard.append(nav_row)

    return InlineKeyboardMarkup(keyboard)


# --- КЛАВИАТУРЫ РАСПИСАНИЯ ---
def get_schedule_days_keyboard() -> InlineKeyboardMarkup:
    days = [
        ("Понедельник", "Monday"), ("Вторник", "Tuesday"),
        ("Среда", "Wednesday"), ("Четверг", "Thursday"),
        ("Пятница", "Friday"), ("Суббота", "Saturday"), ("Воскресенье", "Sunday")
    ]
    keyboard = []
    row = []
    for d_name, d_code in days:
        row.append(InlineKeyboardButton(d_name, callback_data=f"sched_select_day:{d_code}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_manage_hub")])
    return InlineKeyboardMarkup(keyboard)


def get_schedule_edit_keyboard(current_subjects: List[str], all_subjects: List[str],
                               day_code: str) -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    for sub in all_subjects:
        status = "✅" if sub in current_subjects else "⬜"
        text = f"{status} {sub}"
        row.append(InlineKeyboardButton(text, callback_data=f"sched_toggle:{day_code}:{sub}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)

    keyboard.append([InlineKeyboardButton("🔙 К выбору дня", callback_data="admin_schedule_menu")])
    return InlineKeyboardMarkup(keyboard)


# --- КЛАВИАТУРЫ УПРАВЛЕНИЯ ПОЛЕЗНЫМИ МАТЕРИАЛАМИ ---
def get_admin_materials_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("➕ Добавить файл/памятку", callback_data="admin_mat_add_select_sub"),
            InlineKeyboardButton("➖ Удалить файл/памятку", callback_data="admin_mat_remove_select_sub")
        ],
        [
            InlineKeyboardButton("⬅️ Назад в Управление", callback_data="admin_manage_hub")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_user_materials_subjects_keyboard(subjects: List[str], user_class_key: str,
                                         data: Dict[str, Any]) -> InlineKeyboardMarkup:
    """Клавиатура предметов, для которых у данного класса есть загруженные материалы."""
    keyboard = []
    row = []

    class_materials = data.get("materials", {}).get(user_class_key, {})
    active_subjects = [sub for sub in subjects if class_materials.get(sub)]

    for subject in active_subjects:
        row.append(InlineKeyboardButton(subject, callback_data=f"view_mats_for:{subject}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_user_files_list_keyboard(files: List[Dict[str, Any]], subject: str) -> InlineKeyboardMarkup:
    """Отображает список файлов по выбранному предмету."""
    keyboard = []
    for i, file_info in enumerate(files):
        btn_text = f"📄 {file_info.get('name', 'Файл')}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"get_user_file:{subject}:{i}")])

    keyboard.append([InlineKeyboardButton("⬅️ К выбору предметов", callback_data="user_materials_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_admin_remove_files_keyboard(files: List[Dict[str, Any]], subject: str) -> InlineKeyboardMarkup:
    """Выводит список файлов предмета для удаления администратором."""
    keyboard = []
    for i, file_info in enumerate(files):
        btn_text = f"🗑️ Удалить: {file_info.get('name', 'Файл')}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"admin_mat_confirm_remove:{subject}:{i}")])

    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_materials_hub")])
    return InlineKeyboardMarkup(keyboard)


# --- ЛОГИКА АДМИНОВ/ПРЕДМЕТОВ/ЧС/ПЕРЕСЫЛКИ ---
async def process_add_admin(context: ContextTypes.DEFAULT_TYPE, new_admin_id: int) -> str:
    data = load_data()
    if new_admin_id in data["admins"]:
        return f"Пользователь с ID {new_admin_id} уже является администратором."
    data["admins"].append(new_admin_id)
    save_data(data)
    return f"✅ Пользователь с ID {new_admin_id} добавлен в список администраторов."


async def process_remove_admin(context: ContextTypes.DEFAULT_TYPE, admin_to_remove: int) -> str:
    if admin_to_remove == OWNER_ID:
        return "❗ Вы не можете удалить из списка администраторов самого Владельца."
    data = load_data()
    if admin_to_remove not in data["admins"]:
        return f"Пользователя с ID {admin_to_remove} нет в списке администраторов."
    data["admins"].remove(admin_to_remove)
    save_data(data)
    return f"✅ Пользователь с ID {admin_to_remove} удален из списка администраторов."


async def process_add_blacklist(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    if user_id == OWNER_ID:
        return "❌ Вы не можете забанить Владельца."
    data = load_data()
    if user_id in data.get("blacklist", []):
        return f"Пользователь {user_id} уже в ЧС."

    if "blacklist" not in data: data["blacklist"] = []
    data["blacklist"].append(user_id)
    save_data(data)
    return f"⛔ Пользователь `{user_id}` **добавлен** в Чёрный список."


async def process_remove_blacklist(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    data = load_data()
    if "blacklist" not in data: data["blacklist"] = []

    if user_id not in data["blacklist"]:
        return f"Пользователя `{user_id}` нет в ЧС."

    data["blacklist"].remove(user_id)
    save_data(data)
    return f"✅ Пользователь `{user_id}` **удален** из Чёрного списка (разбанен)."


async def process_add_forward(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    data = load_data()
    if "forward_list" not in data: data["forward_list"] = []

    if user_id in data["forward_list"]:
        return f"Пользователь `{user_id}` уже в списке пересылки."

    data["forward_list"].append(user_id)
    save_data(data)
    return f"✅ Пользователь `{user_id}` **добавлен** в список пересылки."


async def process_remove_forward(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    data = load_data()
    if "forward_list" not in data: data["forward_list"] = []

    if user_id not in data["forward_list"]:
        return f"Пользователя `{user_id}` нет в списке пересылки."

    data["forward_list"].remove(user_id)
    save_data(data)
    return f"✅ Пользователь `{user_id}` **удален** из списка пересылки."


async def process_add_subject(context: ContextTypes.DEFAULT_TYPE, new_subject: str) -> str:
    data = load_data()
    subject_title = new_subject.strip().capitalize()
    if subject_title in data["subjects"]:
        return f"Предмет {escape_md(subject_title)} уже есть в списке."
    data["subjects"].append(subject_title)
    save_data(data)
    return f"✅ Предмет {escape_md(subject_title)} добавлен в список."


async def process_remove_subject(context: ContextTypes.DEFAULT_TYPE, subject_to_remove: str) -> str:
    data = load_data()
    subject_title = subject_to_remove.strip().capitalize()
    if subject_title not in data["subjects"]:
        return f"Предмета {escape_md(subject_title)} нет в списке."
    data["subjects"].remove(subject_title)
    save_data(data)
    return f"✅ Предмет {escape_md(subject_title)} удален из списка."


# --- ОБРАБОТЧИКИ КОМАНД ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    if is_blacklisted(update.effective_user.id, data): return

    user = update.effective_user
    user_id_str = str(user.id)

    if "users" not in data:
        data["users"] = {}

    user_data = data["users"].get(user_id_str, {})

    user_data["username"] = user.username
    user_data["first_name"] = user.first_name
    if "points" not in user_data: user_data["points"] = 0
    if "last_claim" not in user_data: user_data["last_claim"] = ""
    if "reaction_group" not in user_data: user_data["reaction_group"] = "default"
    if "last_active" not in user_data:
        user_data["last_active"] = datetime.datetime.now().isoformat()

    data["users"][user_id_str] = user_data
    update_user_activity(user.id, data)
    save_data(data)

    safe_first_name = escape_md(user.first_name)

    user_class_key = get_user_class_key(user.id, data)

    if not user_class_key:
        await update.message.reply_text(
            f"👋 Привет, {safe_first_name}!\n\n"
            "🏫 **Регистрация учебного заведения**\n"
            "Для начала работы выберите тип вашего учебного заведения:",
            reply_markup=get_institution_type_keyboard(),
            parse_mode="Markdown"
        )
    else:
        display_info = get_user_display_info(user.id, data)
        await update.message.reply_text(
            f"Привет! Ваш профиль: **{escape_md(display_info)}** 📚\n"
            "Чтобы открыть меню, используй команду /menu.\n"
            "Для работы с ИИ введите команду: `/ai ваш вопрос`",
            parse_mode=telegram.constants.ParseMode.MARKDOWN
        )


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    if is_blacklisted(update.effective_user.id, data): return

    update_user_activity(update.effective_user.id, data)
    save_data(data)

    start_time = asyncio.get_running_loop().time()
    message = await update.message.reply_text("Pong! 🏓")
    end_time = asyncio.get_running_loop().time()
    ping_ms = (end_time - start_time) * 1000
    await message.edit_text(f"Pong! 🏓\nЗадержка: {ping_ms:.2f}ms", parse_mode=telegram.constants.ParseMode.MARKDOWN)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    if is_blacklisted(update.effective_user.id, data): return

    user_id = update.effective_user.id
    update_user_activity(user_id, data)
    save_data(data)

    user_class_key = get_user_class_key(user_id, data)

    if not user_class_key:
        await start_command(update, context)
        return

    display_info = get_user_display_info(user_id, data)
    reply_markup = get_menu_keyboard(user_id, data)

    if 'next_step' in context.user_data: del context.user_data['next_step']
    if 'hw_context' in context.user_data: del context.user_data['hw_context']
    if 'material_context' in context.user_data: del context.user_data['material_context']

    await update.message.reply_text(
        f"📝 **Главное меню**\n({escape_md(display_info)})\n\nВыберите действие:",
        reply_markup=reply_markup,
        parse_mode=telegram.constants.ParseMode.MARKDOWN
    )


async def show_typing_loop(bot, chat_id, stop_event):
    """Фоновая корутина для постоянного поддержания статуса 'печатает...'."""
    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except Exception as e:
            logger.debug(f"Не удалось отправить chat action: {e}")
        await asyncio.sleep(4.5)  # Статус "typing" в Telegram держится около 5 секунд


async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /ai для генерации ответов от Groq AI."""
    data = load_data()
    if is_blacklisted(update.effective_user.id, data): return

    update_user_activity(update.effective_user.id, data)
    save_data(data)

    if not context.args:
        await update.message.reply_text(
            "🧠 **Запрос к ИИ**\n\n"
            "Напишите ваш вопрос сразу после команды. Пример:\n"
            "`/ai Почему небо голубое?`",
            parse_mode="Markdown"
        )
        return

    user_query = " ".join(context.args)
    chat_id = update.effective_chat.id

    # 1. Отправляем начальное сообщение ожидания
    waiting_msg = await update.message.reply_text("🤔 *Думаю над вашим запросом...*", parse_mode="Markdown")

    # 2. Запускаем фоновую задачу для отображения анимации "печатает..." в чате
    stop_typing_event = asyncio.Event()
    typing_task = asyncio.create_task(show_typing_loop(context.bot, chat_id, stop_typing_event))

    try:
        # 3. Делаем запрос к ИИ
        ai_response = await ask_groq_ai(user_query)
    finally:
        # В любом случае останавливаем анимацию "печатает..."
        stop_typing_event.set()
        await typing_task

    # 4. Удаляем временное сообщение-заглушку
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=waiting_msg.message_id)
    except Exception as e:
        logger.debug(f"Не удалось удалить временное сообщение ИИ: {e}")

    # 5. Разбиваем длинный ответ на части (лимит Telegram - 4096 символов) и отправляем пользователю
    max_tg_length = 4000
    if len(ai_response) <= max_tg_length:
        try:
            await update.message.reply_text(ai_response, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(ai_response)
    else:
        # Если ответ превышает лимит, делим его на фрагменты
        chunks = [ai_response[i:i + max_tg_length] for i in range(0, len(ai_response), max_tg_length)]
        for i, chunk in enumerate(chunks):
            # Добавим подпись к частям для удобства
            caption = f"📖 *[Часть {i + 1}/{len(chunks)}]*\n\n" if len(chunks) > 1 else ""
            try:
                await update.message.reply_text(caption + chunk, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(caption + chunk)
            await asyncio.sleep(0.5)  # Небольшая пауза между отправкой частей


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    if is_blacklisted(update.effective_user.id, data): return

    update_user_activity(update.effective_user.id, data)
    save_data(data)

    if not context.args:
        await update.message.reply_text(
            "❗ **Обратная связь и Помощь**\n\n"
            "• Написать владельцу бота: отправьте команду `/help сообщение`.\n"
            "• Помощник ИИ (Groq): напишите команду `/ai ваш вопрос`.\n\n"
            "Нажмите на команду ниже, чтобы скопировать её:\n"
            "`/help `",
            parse_mode="Markdown"
        )
        return

    message_text = escape_md(" ".join(context.args))
    user = update.effective_user
    cls_info = get_user_display_info(user.id, data)

    admin_text = (
        f"❗**Новое сообщение в поддержку!**\n\n"
        f"👤 **От:** {escape_md(user.full_name)} (@{escape_md(user.username if user.username else 'Нет')})\n"
        f"🆔 **ID:** `{user.id}`\n"
        f"🏫 **Инфо:** {escape_md(cls_info)}\n\n"
        f"📩 **Текст сообщения:**\n{message_text}"
    )

    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=admin_text, parse_mode="Markdown")
        await update.message.reply_text("✅ Ваше сообщение успешно отправлено владельцу!")
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение владельцу: {e}")
        await update.message.reply_text("❌ Произошла ошибка при отправке сообщения.")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    if is_blacklisted(update.effective_user.id, data): return

    update_user_activity(update.effective_user.id, data)
    save_data(data)

    if 'next_step' in context.user_data:
        del context.user_data['next_step']
        if 'hw_context' in context.user_data: del context.user_data['hw_context']
        if 'reaction_context' in context.user_data: del context.user_data['reaction_context']
        if 'material_context' in context.user_data: del context.user_data['material_context']
        context.user_data.pop('dm_target_id', None)
        user_id = update.effective_user.id
        reply_markup = get_menu_keyboard(user_id, data)
        await update.message.reply_text("✅ Действие отменено.", reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text("Нет активного действия для отмены.")


# --- ОБРАБОТЧИКИ CALLBACK-КНОПОК ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    callback_data = query.data

    logger.info(f"Получен callback_data: '{callback_data}' от пользователя {user_id}")

    try:
        data = load_data()
        if is_blacklisted(user_id, data):
            await query.answer()
            return

        update_user_activity(user_id, data)
        save_data(data)

        if update.effective_chat.type != telegram.constants.ChatType.PRIVATE:
            await query.answer("❌ Я работаю только в личных сообщениях!", show_alert=True)
            return

        is_registering = callback_data.startswith("reg_") or callback_data == "ignore"

        if not is_registering:
            user_class_key = get_user_class_key(user_id, data)
            if not user_class_key:
                await query.answer("⚠️ Необходима регистрация", show_alert=True)
                await context.bot.send_message(
                    chat_id=user_id,
                    text="⚠️ **Внимание!**\nНеобходимо обновить информацию о школе.\n\nВыберите тип заведения:",
                    reply_markup=get_institution_type_keyboard(),
                    parse_mode="Markdown"
                )
                try:
                    await query.delete_message()
                except Exception:
                    pass
                return

        try:
            await query.answer()
        except Exception as e:
            logger.warning(f"Не удалось ответить на callback query: {e}")

    except Exception as e:
        logger.error(f"Ошибка на предварительном этапе button_callback: {e}", exc_info=True)
        try:
            await query.answer("❌ Произошла ошибка подключения к базе данных.", show_alert=True)
        except Exception:
            pass
        return

    user_key = str(user_id)
    response_text = ""
    reply_markup = None
    send_photos_after = False

    try:
        if 'next_step' in context.user_data and not callback_data.startswith("navigate_week:"):
            del context.user_data['next_step']

        action_map = {"add": "добавления", "edit": "редактирования", "remove": "удаления", "postpone": "переноса"}

        if callback_data == "ignore":
            return

        # --- РЕГИСТРАЦИЯ ---
        if callback_data == "reg_start":
            response_text = "🏫 **Регистрация**\nВыберите тип учебного заведения:"
            reply_markup = get_institution_type_keyboard()

        elif callback_data.startswith("reg_type:"):
            t_type = callback_data.split(":")[1]
            context.user_data["reg_type"] = t_type
            context.user_data["next_step"] = "waiting_for_school_number"
            response_text = f"Выбрано: **{t_type}**.\n\n🔢 Теперь введите **номер** вашего учебного заведения (например: `1`, `1535`, `57`):"

        elif callback_data.startswith("reg_grade:"):
            grade = callback_data.split(":")[1]
            context.user_data["reg_grade"] = grade
            response_text = f"Выбран класс **{grade}**. Теперь выберите букву:"
            reply_markup = get_reg_letter_keyboard()

        elif callback_data.startswith("reg_letter:"):
            letter = callback_data.split(":")[1]

            reg_type = context.user_data.get("reg_type")
            reg_num = context.user_data.get("reg_num")
            reg_grade = context.user_data.get("reg_grade")

            if not (reg_type and reg_num and reg_grade):
                response_text = "❌ Ошибка данных регистрации. Начните сначала."
                reply_markup = get_institution_type_keyboard()
            else:
                full_class = f"{reg_grade}{letter}"
                if "users" not in data: data["users"] = {}
                if user_key not in data["users"]: data["users"][user_key] = {}

                data["users"][user_key]["inst_type"] = reg_type
                data["users"][user_key]["inst_num"] = reg_num
                data["users"][user_key]["class_name"] = full_class

                revocation_msg = ""
                if user_id in data.get("admins", []) and user_id != OWNER_ID:
                    data["admins"].remove(user_id)
                    revocation_msg = "\n⚠️ **Ваши права администратора были отозваны из-за смены класса/школы.**"

                save_data(data)

                display_info = f"{reg_type} №{reg_num}, {full_class}"
                response_text = f"✅ Успешно! **{escape_md(display_info)}** сохранен!{revocation_msg}\nТеперь вы видите расписание для этой группы."
                reply_markup = get_menu_keyboard(user_id, data)

        # --- ИГРОВАЯ ЛОГИКА ---
        elif callback_data == "game_menu":
            user_info = data["users"].get(user_key, {"points": 0})
            points = user_info.get("points", 0)
            name = user_info.get("first_name", query.from_user.first_name)
            display_info = get_user_display_info(user_id, data)
            response_text = f"🎮 **Ваш Профиль**\n\n👤 Имя: {escape_md(name)}\n🏫 Инфо: **{escape_md(display_info)}**\n💰 Очки: **{points}**"
            reply_markup = get_game_keyboard()

        elif callback_data == "game_claim":
            today_utc = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
            user_info = data["users"].get(user_key, {})

            if not user_info:
                await start_command(update, context)
                return

            last_claim = user_info.get("last_claim", "")

            if last_claim == today_utc:
                response_text = "⏳ Вы уже забирали награду сегодня. Приходите завтра!"
            else:
                reward = random.randint(-5, 10)
                user_info["points"] = user_info.get("points", 0) + reward
                user_info["last_claim"] = today_utc
                data["users"][user_key] = user_info
                save_data(data)
                response_text = f"🎉 Вы получили **{reward}** очков!\n💰 Всего очков: **{user_info['points']}**"

            reply_markup = get_game_keyboard()

        elif callback_data == "game_leaderboard":
            sorted_users = sorted(data["users"].items(), key=lambda item: item[1].get("points", 0), reverse=True)
            top_list = ""
            rank = 1
            for uid, info in sorted_users[:10]:
                name = escape_md(info.get("first_name", f"User {uid}"))
                pts = info.get("points", 0)
                u_info = f"{info.get('class_name', '')}"
                medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"{rank}."
                top_list += f"{medal} {name} ({escape_md(u_info)}) — {pts} 💰\n"
                rank += 1
            if not top_list:
                top_list = "Игроков нет."
            response_text = f"🏆 **Топ игроков**\n\n{top_list}"
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="game_menu")]])

        # --- КАЛЕНДАРЬ И ДЗ ---
        elif callback_data.startswith("navigate_week:"):
            if not is_admin(user_id, data):
                response_text = "❌ У вас нет прав Администратора."
            else:
                _, action_name, new_monday_str = callback_data.split(":")
                new_monday = datetime.datetime.strptime(new_monday_str, "%Y-%m-%d").date()
                user_class_key = get_user_class_key(user_id, data)

                highlight_subject = None
                next_lesson = None
                class_sched = data["schedule"].get(user_class_key, {})

                hw_context = context.user_data.get('hw_context', {})
                highlight_subject = hw_context.get('subject')

                if action_name in ["add", "postpone_target"] and highlight_subject:
                    next_lesson = get_next_lesson_date(highlight_subject, class_sched, datetime.date.today())

                reply_markup = get_day_selection_keyboard(
                    new_monday, action_name, class_sched,
                    highlight_subject=highlight_subject,
                    next_lesson_date=next_lesson
                )

                if action_name in ["postpone_target", "postpone_all_target"]:
                    response_text = "📅 Выберите **НОВУЮ** дату для переноса:"
                elif action_name == "add" and highlight_subject:
                    response_text = f"📅 Выберите дату для добавления ДЗ по **{escape_md(highlight_subject)}** (📌 - есть в расписании):"
                else:
                    response_text = f"Выберите дату для **{action_map.get(action_name, 'действия')}**:"

        elif callback_data.startswith("pick_sub_add:"):
            _, subject = callback_data.split(":", 1)
            user_class_key = get_user_class_key(user_id, data)

            context.user_data['hw_context'] = {'subject': subject, 'action': 'add'}

            today = datetime.date.today()
            monday = get_week_start(today)
            class_sched = data["schedule"].get(user_class_key, {})

            next_lesson = get_next_lesson_date(subject, class_sched, today)

            reply_markup = get_day_selection_keyboard(
                monday, "add", class_sched,
                highlight_subject=subject,
                next_lesson_date=next_lesson
            )
            response_text = f"📅 Выберите дату для добавления ДЗ по **{escape_md(subject)}** (📌 - есть в расписании):"

        elif callback_data.startswith("select_day:"):
            _, action, date_str_iso = callback_data.split(":")
            date_obj = datetime.datetime.strptime(date_str_iso, "%Y-%m-%d").date()
            date_display = date_obj.strftime("%d.%m.%Y")
            user_class_key = get_user_class_key(user_id, data)
            display_info = get_user_display_info(user_id, data)

            if not is_admin(user_id, data):
                response_text = "❌ Нет прав."

            elif action == "add":
                hw_context = context.user_data.get('hw_context', {})
                subject = hw_context.get('subject')

                if not subject:
                    response_text = "❌ Ошибка контекста. Попробуйте снова."
                    reply_markup = get_menu_keyboard(user_id, data)
                else:
                    context.user_data['hw_context']['date'] = date_str_iso
                    context.user_data['next_step'] = 'waiting_for_hw_task'

                    response_text = (
                        f"♻️ **Добавление ДЗ ({escape_md(display_info)}):**\n{date_display} | **{escape_md(subject)}**\n\n"
                        "📝 Отправьте описание или прикрепите фото.")

            elif action == "postpone_target":
                hw_context = context.user_data.get('hw_context')
                if hw_context and hw_context.get('action') == 'postpone_target':
                    old_date = hw_context.get('source_date')
                    subject = hw_context.get('subject')
                    new_date = date_str_iso

                    if (user_class_key in data["homework"] and
                            old_date in data["homework"][user_class_key] and
                            subject in data["homework"][user_class_key][old_date]):

                        entry = data["homework"][user_class_key][old_date].pop(subject)

                        if not data["homework"][user_class_key][old_date]:
                            del data["homework"][user_class_key][old_date]

                        if user_class_key not in data["homework"]: data["homework"][user_class_key] = {}
                        if new_date not in data["homework"][user_class_key]: data["homework"][user_class_key][
                            new_date] = {}

                        data["homework"][user_class_key][new_date][subject] = entry
                        save_data(data)
                        response_text = f"✅ Предмет **{escape_md(subject)}** успешно перенесен\nс {old_date} на **{new_date}**."
                    else:
                        response_text = "⚠️ Ошибка: исходное задание не найдено."

                    reply_markup = get_menu_keyboard(user_id, data)

            elif action == "postpone_all_target":
                hw_context = context.user_data.get('hw_context')
                if hw_context and hw_context.get('action') == 'postpone_all_target':
                    old_date = hw_context.get('source_date')
                    new_date = date_str_iso

                    if user_class_key in data["homework"] and old_date in data["homework"][user_class_key]:
                        if new_date not in data["homework"][user_class_key]:
                            data["homework"][user_class_key][new_date] = {}

                        postponed = data["homework"][user_class_key].pop(old_date)
                        data["homework"][user_class_key][new_date].update(postponed)
                        save_data(data)
                        response_text = f"✅ Всё расписание с {old_date} сдвинуто на **{new_date}**."
                    else:
                        response_text = "⚠️ Нет заданий на исходную дату."

                    reply_markup = get_menu_keyboard(user_id, data)

            elif action in ["edit", "remove", "postpone"]:
                hw_for_date = data["homework"].get(user_class_key, {}).get(date_str_iso, {})
                current_monday = get_week_start(date_obj)

                if not hw_for_date and action != "postpone":
                    response_text = f"⚠️ Для **{escape_md(display_info)}** на **{date_display}** нет ДЗ."
                    class_sched = data["schedule"].get(user_class_key, {})
                    reply_markup = get_day_selection_keyboard(current_monday, action, class_sched)
                else:
                    context.user_data['hw_context'] = {'date': date_str_iso, 'action': action}
                    reply_markup = get_homework_selection_keyboard(date_str_iso, hw_for_date, action)
                    t = {"edit": "Редактирование", "remove": "Удаление", "postpone": "Перенос"}
                    response_text = f"⚙️ **{t.get(action)} ДЗ ({escape_md(display_info)}, {date_display})**"

        # --- ЛОГИКА ОТМЕНЫ УЧЕБНОГО ДНЯ ---
        elif callback_data.startswith("cancel_day:"):
            if not is_admin(user_id, data):
                response_text = "❌ Нет прав."
            else:
                _, date_str = callback_data.split(":", 1)
                user_class_key = get_user_class_key(user_id, data)
                date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()

                if user_class_key in data["homework"] and date_str in data["homework"][user_class_key]:
                    hw_for_date = data["homework"][user_class_key][date_str]
                    class_sched = data["schedule"].get(user_class_key, {})

                    moved_list = []
                    failed_list = []

                    for subject in list(hw_for_date.keys()):
                        entry = hw_for_date[subject]
                        next_lesson_date = get_next_lesson_date(subject, class_sched, date_obj)

                        if next_lesson_date:
                            next_date_str = next_lesson_date.strftime("%Y-%m-%d")

                            if next_date_str not in data["homework"][user_class_key]:
                                data["homework"][user_class_key][next_date_str] = {}

                            existing_entry = data["homework"][user_class_key][next_date_str].get(subject)

                            if existing_entry:
                                old_text = get_hw_text(existing_entry)
                                moved_text = get_hw_text(entry)
                                merged_text = f"{old_text}\n\n[Перенос с {date_obj.strftime('%d.%m')}]:\n{moved_text}".strip()

                                combined_photos = existing_entry.get("photos", []) + entry.get("photos", [])
                                unique_photos = list(dict.fromkeys(combined_photos))

                                data["homework"][user_class_key][next_date_str][subject] = {
                                    "text": merged_text,
                                    "photos": unique_photos
                                }
                            else:
                                data["homework"][user_class_key][next_date_str][subject] = entry

                            del data["homework"][user_class_key][date_str][subject]
                            moved_list.append(f"✅ {escape_md(subject)} ➡️ {next_lesson_date.strftime('%d.%m')}")
                        else:
                            failed_list.append(f"⚠️ {escape_md(subject)} (нет в расписании на 3 недели вперед)")

                    if not data["homework"][user_class_key].get(date_str):
                        if date_str in data["homework"][user_class_key]:
                            del data["homework"][user_class_key][date_str]

                    save_data(data)

                    response_text = f"🔄 **Результат отмены дня ({date_obj.strftime('%d.%m')}):**\n\n"
                    if moved_list:
                        response_text += "\n".join(moved_list) + "\n\n"
                    if failed_list:
                        response_text += "**Не удалось перенести:**\n" + "\n".join(failed_list) + "\n\n"

                    if not failed_list:
                        response_text += "✨ Все задания успешно распределены по следующим урокам!"
                    else:
                        response_text += "❗ Задания, которые не удалось перенести, оставлены на старой дате."
                else:
                    response_text = "⚠️ Заданий на эту дату не найдено."

                reply_markup = get_menu_keyboard(user_id, data)

        elif callback_data.startswith("select_hw_for_"):
            if not is_admin(user_id, data):
                response_text = "❌ Нет прав."
            else:
                parts = callback_data.split(":", 3)
                action, date_str, subject = parts[0].replace("select_hw_for_", ""), parts[1], parts[2]
                user_class_key = get_user_class_key(user_id, data)
                display_info = get_user_display_info(user_id, data)

                context.user_data['hw_context'] = {'date': date_str, 'subject': subject, 'action': action}

                if action == 'edit':
                    context.user_data['next_step'] = 'waiting_for_edited_task'
                    response_text = f"📝 **Редактирование** ({escape_md(display_info)} / {escape_md(subject)}):\n✏️ Отправьте НОВОЕ ИСПРАВЛЕННОЕ задание (текст или фото)."
                elif action == 'remove':
                    response_text = f"🗑️ **Удалить {escape_md(subject)}**?"
                    reply_markup = InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Удалить",
                                              callback_data=f"confirm_remove_subject:{date_str}:{subject}")],
                        [InlineKeyboardButton("❌ Отмена", callback_data="admin_removehw")]
                    ])
                elif action == 'postpone':
                    context.user_data['hw_context'] = {
                        'source_date': date_str,
                        'subject': subject,
                        'action': 'postpone_target'
                    }
                    today = datetime.date.today()
                    monday = get_week_start(today)

                    class_sched = data["schedule"].get(user_class_key, {})
                    next_lesson = get_next_lesson_date(subject, class_sched, today)

                    reply_markup = get_day_selection_keyboard(
                        monday, "postpone_target", class_sched,
                        highlight_subject=subject,
                        next_lesson_date=next_lesson
                    )
                    response_text = f"➡️ Перенос: **{escape_md(subject)}**\n📅 Выберите **новую дату**, куда поставить это задание:"

        elif callback_data.startswith("confirm_remove_subject:"):
            if is_admin(user_id, data):
                _, date_str, subject = callback_data.split(":", 3)
                user_class_key = get_user_class_key(user_id, data)

                if (user_class_key in data["homework"] and
                        date_str in data["homework"][user_class_key] and
                        subject in data["homework"][user_class_key][date_str]):

                    del data["homework"][user_class_key][date_str][subject]
                    if not data["homework"][user_class_key][date_str]:
                        del data["homework"][user_class_key][date_str]

                    save_data(data)
                    response_text = f"✅ Задание по **{escape_md(subject)}** удалено."
                else:
                    response_text = "⚠️ Задание не найдено."
                reply_markup = get_menu_keyboard(user_id, data)

        elif callback_data.startswith("confirm_remove_all:"):
            if is_admin(user_id, data):
                _, date_str = callback_data.split(":", 2)
                user_class_key = get_user_class_key(user_id, data)

                if user_class_key in data["homework"] and date_str in data["homework"][user_class_key]:
                    del data["homework"][user_class_key][date_str]
                    save_data(data)
                    response_text = f"✅ Все задания на эту дату удалены."
                else:
                    response_text = "⚠️ Заданий не найдено."
                reply_markup = get_menu_keyboard(user_id, data)

        elif callback_data.startswith("confirm_postpone_all:"):
            if is_admin(user_id, data):
                _, date_str = callback_data.split(":", 2)
                user_class_key = get_user_class_key(user_id, data)

                if user_class_key in data["homework"] and date_str in data["homework"][user_class_key]:
                    context.user_data['hw_context'] = {
                        'source_date': date_str,
                        'action': 'postpone_all_target'
                    }
                    today = datetime.date.today()
                    monday = get_week_start(today)

                    class_sched = data["schedule"].get(user_class_key, {})
                    reply_markup = get_day_selection_keyboard(monday, "postpone_all_target", class_sched)
                    response_text = f"➡️ **Сдвиг расписания**\n📅 Выберите **НОВУЮ** дату, куда перенести ВСЕ задания с {date_str}:"
                else:
                    response_text = "⚠️ Заданий нет."
                    reply_markup = get_menu_keyboard(user_id, data)

        # --- ОБРАБОТКА CALLBACK ДЛЯ ПОЛЕЗНЫХ МАТЕРИАЛОВ ---
        elif callback_data == "user_materials_menu":
            user_class_key = get_user_class_key(user_id, data)
            display_info = get_user_display_info(user_id, data)

            class_mats = data.get("materials", {}).get(user_class_key, {})
            active_subjects = [sub for sub in data["subjects"] if class_mats.get(sub)]

            if not active_subjects:
                response_text = f"📚 **Полезные материалы ({escape_md(display_info)})**\n\nЗдесь пока пусто. Администраторы класса ещё не загрузили учебные материалы."
                reply_markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("⬅️ Назад в меню", callback_data="back_to_menu")]])
            else:
                response_text = f"📚 **Полезные материалы ({escape_md(display_info)})**\n\nВыберите интересующий предмет для просмотра файлов:"
                reply_markup = get_user_materials_subjects_keyboard(data["subjects"], user_class_key, data)

        elif callback_data.startswith("view_mats_for:"):
            _, subject = callback_data.split(":")
            user_class_key = get_user_class_key(user_id, data)

            files = data.get("materials", {}).get(user_class_key, {}).get(subject, [])
            response_text = f"📚 Предмет: **{escape_md(subject)}**\n\nНиже представлены доступные шпаргалки и файлы. Нажмите на название файла, чтобы скачать его:"
            reply_markup = get_user_files_list_keyboard(files, subject)

        elif callback_data.startswith("get_user_file:"):
            _, subject, idx_str = callback_data.split(":")
            idx = int(idx_str)
            user_class_key = get_user_class_key(user_id, data)

            files = data.get("materials", {}).get(user_class_key, {}).get(subject, [])
            if 0 <= idx < len(files):
                file_info = files[idx]
                file_id = file_info["file_id"]
                caption = f"📚 **{escape_md(file_info['name'])}** (по предмету: {escape_md(subject)})\n\n📝 _Описание: {escape_md(file_info.get('description', 'Без описания'))}_"

                try:
                    await context.bot.send_document(chat_id=user_id, document=file_id, caption=caption,
                                                    parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Не удалось отправить документ: {e}")
                    await context.bot.send_message(chat_id=user_id,
                                                   text="❌ К сожалению, произошла ошибка при загрузке этого файла.")
            else:
                response_text = "❌ Файл не найден в базе данных."
                reply_markup = get_user_materials_subjects_keyboard(data["subjects"], user_class_key, data)

        # --- СПЕЦИФИЧЕСКИЕ КОМАНДЫ ПОЛЕЗНЫХ МАТЕРИАЛОВ ---
        elif callback_data.startswith("admin_mat_add_to_sub:"):
            _, subject = callback_data.split(":")
            context.user_data["material_context"] = {"subject": subject}
            context.user_data["next_step"] = "waiting_for_material_file"

            response_text = f"📚 **Загрузка материала по предмету: {escape_md(subject)}**\n\n📂 Отправьте любой учебный файл (документ PDF, DOCX, презентацию или обычное изображение), который вы хотите сохранить."

        elif callback_data.startswith("admin_mat_remove_from_sub:"):
            _, subject = callback_data.split(":")
            user_class_key = get_user_class_key(user_id, data)

            files = data.get("materials", {}).get(user_class_key, {}).get(subject, [])
            response_text = f"🗑️ **Удаление файлов по предмету: {escape_md(subject)}**\n\nВыберите файл из списка, который хотите навсегда удалить:"
            reply_markup = get_admin_remove_files_keyboard(files, subject)

        elif callback_data.startswith("admin_mat_confirm_remove:"):
            _, subject, idx_str = callback_data.split(":")
            idx = int(idx_str)
            user_class_key = get_user_class_key(user_id, data)

            if (user_class_key in data.get("materials", {}) and
                    subject in data["materials"][user_class_key] and
                    0 <= idx < len(data["materials"][user_class_key][subject])):

                removed_file = data["materials"][user_class_key][subject].pop(idx)
                if not data["materials"][user_class_key][subject]:
                    del data["materials"][user_class_key][subject]
                if not data["materials"][user_class_key]:
                    del data["materials"][user_class_key]

                save_data(data)
                response_text = f"✅ Файл **{escape_md(removed_file['name'])}** успешно удалён."
            else:
                response_text = "⚠️ Файл не найден или уже был удалён."

            reply_markup = get_admin_materials_keyboard()

        # --- ЛОГИКА РЕДАКТИРОВАНИЯ РАСПИСАНИЯ ---
        elif callback_data.startswith("sched_"):
            if not is_admin(user_id, data):
                response_text = "❌ Только для админов."
            else:
                user_class_key = get_user_class_key(user_id, data)
                display_info = get_user_display_info(user_id, data)

                if not user_class_key:
                    response_text = "❌ У вас не выбран класс."
                else:
                    sub_action = callback_data.replace("sched_", "")

                    if sub_action.startswith("select_day:"):
                        day_code = sub_action.split(":")[1]

                        if user_class_key not in data["schedule"]: data["schedule"][user_class_key] = {}
                        current_sched = data["schedule"][user_class_key].get(day_code, [])

                        response_text = f"📅 **Редактирование расписания**\n({escape_md(display_info)})\nДень: {day_code}\n\nВключите предметы:"
                        reply_markup = get_schedule_edit_keyboard(current_sched, data["subjects"], day_code)

                    elif sub_action.startswith("toggle:"):
                        _, day_code, subject = sub_action.split(":", 2)

                        if user_class_key not in data["schedule"]: data["schedule"][user_class_key] = {}
                        if day_code not in data["schedule"][user_class_key]: data["schedule"][user_class_key][
                            day_code] = []

                        current_list = data["schedule"][user_class_key][day_code]

                        if subject in current_list:
                            current_list.remove(subject)
                        else:
                            current_list.append(subject)

                        data["schedule"][user_class_key][day_code] = current_list
                        save_data(data)

                        response_text = f"📅 **Редактирование расписания**\n({escape_md(display_info)})\nДень: {day_code}\n\nВключите предметы:"
                        reply_markup = get_schedule_edit_keyboard(current_list, data["subjects"], day_code)

        # --- ЛИЧНОЕ СООБЩЕНИЕ ОТ ВЛАДЕЛЬЦА ---
        elif callback_data.startswith("dm_page:"):
            if not is_owner(user_id):
                response_text = "❌ Только владелец."
            else:
                page = int(callback_data.split(":")[1])
                response_text = "✉️ **Кому отправить сообщение?**\n\nВыберите пользователя из списка:"
                reply_markup = get_users_list_keyboard(data, page)

        elif callback_data.startswith("dm_user:"):
            if not is_owner(user_id):
                response_text = "❌ Только владелец."
            else:
                target_id = callback_data.split(":")[1]
                target_data = data["users"].get(target_id, {})
                name = target_data.get("first_name") or "Без имени"
                username = target_data.get("username")

                context.user_data['next_step'] = 'waiting_for_dm_message'
                context.user_data['dm_target_id'] = target_id

                recipient = f"{name} (@{username})" if username else name
                response_text = (
                    f"✉️ **Сообщение для {escape_md(recipient)}**\n"
                    f"🆔 ID: `{target_id}`\n\n"
                    "Отправьте текст (можно с фото) — он придёт пользователю как есть, "
                    "без уведомления и служебных подписей.\n"
                    "Напишите /cancel для отмены."
                )

        # --- ОБЩИЙ ОБРАБОТЧИК АДМИН-ПАНЕЛИ ---
        elif callback_data.startswith("admin_"):
            action_parts = callback_data.split("_")

            if not is_admin(user_id, data) and not is_owner(user_id):
                response_text = "❌ Нет прав."
            else:
                action = action_parts[1]

                # --- ЛИЧНОЕ СООБЩЕНИЕ ОТ ВЛАДЕЛЬЦА ---
                if action == "dm" and action_parts[2] == "menu":
                    if not is_owner(user_id):
                        response_text = "❌ Только владелец."
                    else:
                        response_text = "✉️ **Кому отправить сообщение?**\n\nВыберите пользователя из списка:"
                        reply_markup = get_users_list_keyboard(data, 0)

                # --- УПРАВЛЕНИЕ РЕАКЦИЯМИ ---
                elif action == "reactions" and action_parts[2] == "menu":
                    if not is_owner(user_id):
                        response_text = "❌ Только владелец."
                    else:
                        response_text = "🎭 **Управление Реакциями**\n\nЗдесь вы можете создавать группы реакций, менять эмодзи и назначать пользователей."
                        reply_markup = get_reaction_menu_keyboard()

                elif action == "react" and action_parts[2] == "create":
                    if not is_owner(user_id):
                        response_text = "❌ Только владелец."
                    else:
                        context.user_data['next_step'] = 'waiting_for_react_group_name'
                        response_text = "🆕 Введите название новой группы реакций (на английском, например: `vip`, `haters`):"

                elif action == "react" and action_parts[2] == "delete":
                    if not is_owner(user_id):
                        response_text = "❌ Только владелец."
                    else:
                        response_text = "🗑️ Выберите группу для удаления:"
                        reply_markup = get_reaction_groups_list_keyboard(data, "delete_react_group")

                elif action == "react" and action_parts[2] == "edit":
                    if not is_owner(user_id):
                        response_text = "❌ Только владелец."
                    else:
                        response_text = "✏️ Выберите группу, чтобы изменить её эмодзи:"
                        reply_markup = get_reaction_groups_list_keyboard(data, "edit_react_emojis")

                elif action == "react" and action_parts[2] == "assign":
                    if not is_owner(user_id):
                        response_text = "❌ Только владелец."
                    else:
                        context.user_data['next_step'] = 'waiting_for_user_id_react_assign'
                        response_text = "👤 Введите **ID пользователя**, которого вы хотите назначить в группу:"

                elif action == "react" and action_parts[2] == "view":
                    if not is_owner(user_id):
                        response_text = "❌ Только владелец."
                    else:
                        text_out = "🎭 **Группы реакций:**\n\n"
                        for gname, emojis in data.get("reaction_groups", {}).items():
                            emo_str = " ".join(emojis)
                            text_out += f"🔹 **{gname}**: {emo_str}\n"
                        response_text = text_out
                        reply_markup = InlineKeyboardMarkup(
                            [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_reactions_menu")]])

                # --- ПЕРЕСЫЛКА ---
                elif action == "forward" and action_parts[2] == "menu":
                    if not is_owner(user_id):
                        response_text = "❌ Только владелец."
                    else:
                        response_text = "📨 **Управление Пересылкой**\n\nСообщения от пользователей в этом списке будут пересылаться вам."
                        reply_markup = get_forward_menu_keyboard()

                elif action == "forward" and action_parts[2] in ["add", "remove"] and action_parts[3] == "prompt":
                    if not is_owner(user_id):
                        response_text = "❌ Только владелец."
                    else:
                        sub_act = action_parts[2]
                        t = "добавить" if sub_act == "add" else "удалить"
                        context.user_data['next_step'] = f'waiting_for_forward_{sub_act}'
                        response_text = f"📨 Введите **ID пользователя**, чтобы {t} его из списка пересылки:"

                elif action == "forward" and action_parts[2] == "view":
                    if not is_owner(user_id):
                        response_text = "❌ Только владелец."
                    else:
                        fw_ids = data.get("forward_list", [])
                        if not fw_ids:
                            response_text = "📨 **Список пересылки пуст.**"
                        else:
                            response_text = "📨 **Список пересылки:**\n\n"
                            for f_id in fw_ids:
                                u_info = data["users"].get(str(f_id), {})
                                fname = escape_md(u_info.get('first_name', 'Unknown'))
                                uname = f"@{escape_md(u_info.get('username', 'NoUser'))}" if u_info.get(
                                    'username') else "NoUsername"
                                response_text += f"🆔 `{f_id}` | {uname} | {fname}\n"
                        reply_markup = InlineKeyboardMarkup(
                            [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_forward_menu")]])

                # --- ОЧИСТКА СТАРОГО ДЗ ---
                elif action == "cleanup" and action_parts[2] == "prompt":
                    if not is_admin(user_id, data):
                        response_text = "❌ Только администраторы."
                    else:
                        first_of_month = datetime.date.today().replace(day=1)
                        response_text = f"🗑️ **Очистка базы данных**\n\nВы уверены, что хотите удалить ВСЕ домашние задания старше **{first_of_month.strftime('%d.%m.%Y')}**?\n\nЭто действие нельзя отменить."
                        reply_markup = InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅ ДА, УДАЛИТЬ", callback_data="admin_confirm_cleanup")],
                            [InlineKeyboardButton("❌ НЕТ, ОТМЕНА", callback_data="admin_manage_hub")]
                        ])

                elif action == "confirm" and action_parts[2] == "cleanup":
                    if not is_admin(user_id, data):
                        response_text = "❌ Только администраторы."
                    else:
                        count_deleted = 0
                        cutoff_date = datetime.date.today().replace(day=1)

                    for cls_name in list(data["homework"].keys()):
                        class_hw = data["homework"][cls_name]
                        for date_key in list(class_hw.keys()):
                            try:
                                d = datetime.datetime.strptime(date_key, "%Y-%m-%d").date()
                                if d < cutoff_date:
                                    del data["homework"][cls_name][date_key]
                                    count_deleted += 1
                            except ValueError:
                                pass

                        save_data(data)
                        response_text = f"✅ База данных очищена.\nУдалено записей (дней): **{count_deleted}**."
                        reply_markup = InlineKeyboardMarkup(
                            [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_manage_hub")]])

                elif action == "schedule" and action_parts[2] == "menu":
                    user_class_key = get_user_class_key(user_id, data)
                    display_info = get_user_display_info(user_id, data)
                    if not user_class_key:
                        response_text = "❌ У вас не выбран класс."
                    else:
                        response_text = f"📅 **Управление расписанием**\n({escape_md(display_info)})\nВыберите день недели:"
                        reply_markup = get_schedule_days_keyboard()

                elif action == "broadcast" and action_parts[2] == "prompt":
                    if not is_admin(user_id, data):
                        response_text = "❌ Только администраторы могут делать рассылку."
                    else:
                        context.user_data['next_step'] = 'waiting_for_broadcast_message'
                        response_text = (
                            "📢 **РАССЫЛКА ВСЕМ ПОЛЬЗОВАТЕЛЯМ**\n\n"
                            "Отправьте текст (можно с фото), который вы хотите разослать.\n"
                            "⚠️ Это действие нельзя отменить.\n"
                            "Напишите /cancel для отмены."
                        )

                elif action == "stats":
                    if not is_owner(user_id):
                        response_text = "❌ Только владелец."
                    else:
                        total_users = len(data["users"])
                        active_24h = 0

                        now = datetime.datetime.now()
                        threshold = now - datetime.timedelta(hours=24)

                        for uid, udata in data["users"].items():
                            last_active_str = udata.get("last_active")
                            if last_active_str:
                                try:
                                    last_dt = datetime.datetime.fromisoformat(last_active_str)
                                    if last_dt > threshold:
                                        active_24h += 1
                                except ValueError:
                                    pass

                        response_text = (
                            f"📊 **Статистика бота:**\n\n"
                            f"👥 Всего пользователей: **{total_users}**\n"
                            f"🟢 Активных за 24ч: **{active_24h}**"
                        )
                        reply_markup = InlineKeyboardMarkup(
                            [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_manage_hub")]])

                elif action == "manage" and action_parts[2] == "hub":
                    response_text = "🛠️ **Центр управления**"
                    reply_markup = get_admin_hub_keyboard(user_id, data)

                elif action == "manage" and action_parts[2] == "users":
                    if not is_owner(user_id):
                        response_text = "❌ Только владелец."
                    else:
                        response_text = "🔑 **Управление Админами**"
                        reply_markup = InlineKeyboardMarkup([
                            [InlineKeyboardButton("➕ Добавить Админа", callback_data="admin_add_prompt"),
                             InlineKeyboardButton("➖ Удалить Админа", callback_data="admin_remove_prompt")],
                            [InlineKeyboardButton("👀 Список Админов", callback_data="admin_view_admins")],
                            [InlineKeyboardButton("⬅️ Назад", callback_data="admin_manage_hub")]
                        ])

                elif action == "blacklist" and action_parts[2] == "menu":
                    if not is_owner(user_id):
                        response_text = "❌ Только владелец."
                    else:
                        response_text = "⛔ **Управление Чёрным Списком**"
                        reply_markup = get_blacklist_menu_keyboard()

                elif action == "blacklist" and action_parts[2] == "view":
                    if not is_owner(user_id):
                        response_text = "❌ Только владелец."
                    else:
                        blacklist_ids = data.get("blacklist", [])
                        if not blacklist_ids:
                            response_text = "⛔ **Чёрный список пуст.**"
                        else:
                            response_text = "⛔ **Чёрный список:**\n\n"
                            for b_id in blacklist_ids:
                                u_info = data["users"].get(str(b_id), {})
                                uname = f"@{escape_md(u_info.get('username', 'NoUser'))}" if u_info.get(
                                    'username') else "NoUsername"
                                fname = escape_md(u_info.get('first_name', 'Unknown'))
                                response_text += f"🆔 `{b_id}` | {uname} | {fname}\n"
                        reply_markup = InlineKeyboardMarkup(
                            [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_blacklist_menu")]])

                elif action == "blacklist" and action_parts[2] in ["add", "remove"] and action_parts[3] == "prompt":
                    if not is_owner(user_id):
                        response_text = "❌ Только владелец."
                    else:
                        sub_act = action_parts[2]
                        t = "забанить" if sub_act == "add" else "разбанить"
                        context.user_data['next_step'] = f'waiting_for_blacklist_{sub_act}'
                        response_text = f"⛔ Введите **ID пользователя**, чтобы {t} его:"

                elif action in ["addhw", "edithw", "removehw", "postponehw"]:
                    user_class_key = get_user_class_key(user_id, data)
                    display_info = get_user_display_info(user_id, data)
                    if not user_class_key:
                        response_text = "❌ У вас не выбран класс."
                    else:
                        cmd = action.replace("hw", "")

                        if cmd == "add":
                            response_text = "Выберите предмет для добавления ДЗ:"
                            if not data["subjects"]:
                                response_text = "❌ Список предметов пуст. Добавьте предметы в Админ-панели."
                                reply_markup = get_menu_keyboard(user_id, data)
                            else:
                                reply_markup = get_simple_subject_list_keyboard(data["subjects"], "pick_sub_add")
                        else:
                            response_text = f"Действие для **{escape_md(display_info)}**. Выберите дату:"
                            class_sched = data["schedule"].get(user_class_key, {})
                            reply_markup = get_day_selection_keyboard(get_week_start(datetime.date.today()), cmd,
                                                                      class_sched)

                elif action == "manage" and action_parts[2] == "subjects":
                    response_text = "📚 **Управление Предметами**"
                    reply_markup = get_subject_management_keyboard()
                elif action == "subject" and action_parts[2] == "view":
                    subs = "\n".join([f"• {escape_md(s)}" for s in data["subjects"]])
                    response_text = f"📚 **Предметы:**\n{subs}"
                    reply_markup = get_subject_management_keyboard()
                elif action == "subject" and action_parts[2] in ["add", "remove"] and action_parts[-1] == "prompt":
                    t = "добавления" if action_parts[2] == "add" else "удаления"
                    context.user_data['next_step'] = f'waiting_for_subject_to_{action_parts[2]}'
                    response_text = f"**Введите название предмета для {t}:**"

                elif action in ["add", "remove"] and action_parts[-1] == "prompt":
                    if not is_owner(user_id):
                        response_text = "❌ Только владелец."
                    else:
                        t = "добавления" if action == "add" else "удаления"
                        context.user_data['next_step'] = f'waiting_for_admin_id_to_{action}'
                        response_text = f"**Введите ID Администратора для {t}:**"

                elif action == "view" and action_parts[2] == "admins":
                    if not is_owner(user_id):
                        response_text = "❌ Только владелец."
                    else:
                        admin_ids = data.get("admins", [])
                        response_text = f"🔑 **Администраторы ({len(admin_ids)}):**\n\n"
                        for a_id in admin_ids:
                            role = "👑 ВЛАДЕЛЕЦ" if a_id == OWNER_ID else "👮‍♂️ Админ"
                            u_info = data["users"].get(str(a_id), {})
                            uname = f"@{escape_md(u_info.get('username', 'NoUser'))}" if u_info.get(
                                'username') else "NoUsername"
                            fname = escape_md(u_info.get('first_name', 'Unknown'))
                            response_text += f"🆔 `{a_id}` | {uname} | {fname} | {role}\n"

                        reply_markup = InlineKeyboardMarkup(
                            [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_manage_users")]])

                elif action == "materials" and action_parts[2] == "hub":
                    response_text = "📚 **Управление файлами и памятками**\n\nЗдесь вы можете загружать шпаргалки и документы для своего класса по конкретным предметам."
                    reply_markup = get_admin_materials_keyboard()

                elif action == "mat" and action_parts[2] == "add" and action_parts[3] == "select" and action_parts[
                    4] == "sub":
                    response_text = "Выберите предмет, для которого вы хотите добавить полезный материал:"
                    reply_markup = get_simple_subject_list_keyboard(data["subjects"], "admin_mat_add_to_sub")

                elif action == "mat" and action_parts[2] == "remove" and action_parts[3] == "select" and action_parts[
                    4] == "sub":
                    user_class_key = get_user_class_key(user_id, data)
                    if not user_class_key:
                        response_text = "❌ У вас не выбран класс."
                        reply_markup = get_admin_materials_keyboard()
                    else:
                        response_text = "Выберите предмет, чтобы посмотреть загруженные файлы для удаления:"
                        class_mats = data.get("materials", {}).get(user_class_key, {})
                        active_subjects = [sub for sub in data["subjects"] if class_mats.get(sub)]

                        if not active_subjects:
                            response_text = "📚 **Список файлов пуст.** У вашего класса ещё нет загруженных памяток."
                            reply_markup = get_admin_materials_keyboard()
                        else:
                            reply_markup = get_simple_subject_list_keyboard(active_subjects,
                                                                            "admin_mat_remove_from_sub")

        # --- РАБОТА С ГРУППАМИ РЕАКЦИЙ ---
        elif callback_data.startswith("delete_react_group:"):
            if is_owner(user_id):
                _, group_name = callback_data.split(":", 1)
                if group_name == "default":
                    response_text = "❌ Нельзя удалить группу `default`."
                elif group_name in data.get("reaction_groups", {}):
                    del data["reaction_groups"][group_name]
                    save_data(data)
                    response_text = f"🗑️ Группа **{escape_md(group_name)}** удалена."
                else:
                    response_text = "⚠️ Группа не найдена."
                reply_markup = get_reaction_menu_keyboard()

        elif callback_data.startswith("edit_react_emojis:"):
            if is_owner(user_id):
                _, group_name = callback_data.split(":", 1)
                context.user_data["reaction_context"] = {"group": group_name}

                if group_name in data.get("reaction_groups", {}):
                    current_emojis = data["reaction_groups"][group_name]
                    response_text = f"✏️ Редактирование эмодзи для **{escape_md(group_name)}**.\n\nНажмите на эмодзи, чтобы включить/выключить его:"
                    reply_markup = get_emoji_selection_keyboard(group_name, current_emojis, 0)
                else:
                    response_text = "❌ Группа не найдена."
                    reply_markup = get_reaction_menu_keyboard()

        elif callback_data.startswith("react_toggle:"):
            if is_owner(user_id):
                _, group_name, page_str, emoji_char = callback_data.split(":", 3)
                page = int(page_str)

                if group_name in data.get("reaction_groups", {}):
                    current_list = data["reaction_groups"][group_name]

                    if emoji_char in current_list:
                        current_list.remove(emoji_char)
                    else:
                        current_list.append(emoji_char)

                    data["reaction_groups"][group_name] = current_list
                    save_data(data)

                    response_text = f"✏️ Редактирование эмодзи для **{escape_md(group_name)}**.\n\nНажмите на эмодзи, чтобы включить/выключить его:"
                    reply_markup = get_emoji_selection_keyboard(group_name, current_list, page)
                else:
                    response_text = "❌ Группа не найдена."
                    reply_markup = get_reaction_menu_keyboard()

        elif callback_data.startswith("react_page:"):
            if is_owner(user_id):
                _, group_name, page_str = callback_data.split(":", 2)
                page = int(page_str)

                if group_name in data.get("reaction_groups", {}):
                    current_list = data["reaction_groups"][group_name]
                    response_text = f"✏️ Редактирование эмодзи для **{escape_md(group_name)}**.\n\nНажмите на эмодзи, чтобы включить/выключить его:"
                    reply_markup = get_emoji_selection_keyboard(group_name, current_list, page)
                else:
                    response_text = "❌ Группа не найдена."
                    reply_markup = get_reaction_menu_keyboard()

        elif callback_data.startswith("assign_react_group:"):
            if is_owner(user_id):
                _, group_name = callback_data.split(":", 1)
                target_user_id = context.user_data.get("reaction_context", {}).get("target_user_id")

                if target_user_id:
                    target_user_str = str(target_user_id)
                    if "users" not in data: data["users"] = {}
                    if target_user_str not in data["users"]:
                        data["users"][target_user_str] = {}

                    data["users"][target_user_str]["reaction_group"] = group_name
                    save_data(data)
                    response_text = f"✅ Пользователь `{target_user_id}` назначен в группу **{escape_md(group_name)}**."
                else:
                    response_text = "⚠️ Ошибка контекста."

                reply_markup = get_reaction_menu_keyboard()

        elif callback_data == "view_hw":
            user_class_key = get_user_class_key(user_id, data)
            if not user_class_key: return

            display_dates = get_display_weeks()
            display_info = get_user_display_info(user_id, data)

            class_hw = data["homework"].get(user_class_key, {})
            class_schedule = data["schedule"].get(user_class_key, {})

            response_text = format_hw_for_display(class_hw, class_schedule, display_dates, display_info)
            reply_markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Назад в меню", callback_data="back_to_menu")]])
            send_photos_after = True

        elif callback_data == "view_hw_past":
            user_class_key = get_user_class_key(user_id, data)
            if not user_class_key: return

            display_info = get_user_display_info(user_id, data)
            today = datetime.date.today()
            past_dates = [today - datetime.timedelta(days=i) for i in range(7, 0, -1)]

            class_hw = data["homework"].get(user_class_key, {})
            class_schedule = data["schedule"].get(user_class_key, {})

            response_text = f"🗄️ **АРХИВ ДЗ (Последние 7 дней)**\n{escape_md(display_info)}\n\n"
            response_text += format_hw_for_display(class_hw, class_schedule, past_dates, display_info)
            reply_markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Назад в меню", callback_data="back_to_menu")]])
            send_photos_after = True

        elif callback_data == "back_to_menu":
            if 'hw_context' in context.user_data: del context.user_data['hw_context']
            if 'reaction_context' in context.user_data: del context.user_data['reaction_context']
            if 'material_context' in context.user_data: del context.user_data['material_context']

            await cleanup_hw_photos(context, user_id)

            user_class_key = get_user_class_key(user_id, data)
            display_info = get_user_display_info(user_id, data)
            if not user_class_key: return

            reply_markup = get_menu_keyboard(user_id, data)
            response_text = f"📝 **Главное меню**\n({escape_md(display_info)})"

    except Exception as e:
        logger.error(f"Критическая ошибка при обработке callback_data '{callback_data}': {e}", exc_info=True)
        response_text = "❌ Произошла ошибка при обработке команды. Пожалуйста, откройте меню заново с помощью /menu."
        reply_markup = None

    if response_text:
        try:
            await query.edit_message_text(text=response_text, reply_markup=reply_markup,
                                          parse_mode=telegram.constants.ParseMode.MARKDOWN)
        except Exception:
            try:
                await context.bot.send_message(chat_id=user_id, text=response_text, reply_markup=reply_markup,
                                               parse_mode=telegram.constants.ParseMode.MARKDOWN)
            except Exception as e:
                logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

    if send_photos_after:
        if callback_data == "view_hw_past":
            today = datetime.date.today()
            display_dates = [today - datetime.timedelta(days=i) for i in range(7, 0, -1)]
        else:
            display_dates = get_display_weeks()

        user_class_key = get_user_class_key(user_id, data)
        class_hw = data["homework"].get(user_class_key, {})
        await send_schedule_photos(context, user_id, class_hw, display_dates)


# --- ОБРАБОТЧИК ВВОДНЫХ СООБЩЕНИЙ ---
async def handle_message_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    if is_blacklisted(update.effective_user.id, data): return

    user = update.effective_user
    user_id = user.id
    update_user_activity(user_id, data)
    save_data(data)

    input_text = update.message.text or update.message.caption or ""
    input_text = input_text.strip()
    photo_id = update.message.photo[-1].file_id if update.message.photo else None

    document = update.message.document
    document_id = document.file_id if document else None
    document_name = document.file_name if document else None

    next_step = context.user_data.get('next_step')
    result_message = ""
    is_media_group = update.message.media_group_id is not None

    # --- ЛОГИКА АВТО-РЕАКЦИЙ И ПЕРЕСЫЛКИ (БЕЗ КОНТЕКСТА) ---
    if not next_step:
        if user_id != OWNER_ID and user_id in data.get("forward_list", []):
            try:
                await context.bot.forward_message(chat_id=OWNER_ID, from_chat_id=user_id, message_id=update.message.id)
                user_info_str = f"👆 Сообщение от {escape_md(user.full_name)} (ID: `{user_id}`)"
                if user.username:
                    user_info_str += f" @{escape_md(user.username)}"
                await context.bot.send_message(chat_id=OWNER_ID, text=user_info_str, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Ошибка пересылки сообщения от {user_id}: {e}")

        user_group = data["users"].get(str(user_id), {}).get("reaction_group", "default")
        if user_group not in data.get("reaction_groups", {}):
            user_group = "default"

        emojis = data.get("reaction_groups", {}).get(user_group, ["👍"])
        if emojis:
            chosen_emoji = random.choice(emojis)
            try:
                await update.message.set_reaction(chosen_emoji)
            except Exception:
                pass
        return

    # --- ВВОД НОМЕРА ШКОЛЫ ---
    if next_step == 'waiting_for_school_number':
        if not input_text:
            await update.message.reply_text("❗ Введите номер школы текстом или числом.")
            return

        context.user_data["reg_num"] = input_text
        del context.user_data["next_step"]

        await update.message.reply_text(
            f"Номер сохранен: **{escape_md(input_text)}**.\nТеперь выберите цифру класса:",
            reply_markup=get_reg_grade_keyboard(),
            parse_mode="Markdown"
        )
        return

    # --- РАССЫЛКА ---
    elif next_step == 'waiting_for_broadcast_message':
        if not is_admin(user_id, data):
            result_message = "❌ Ошибка прав доступа."
        else:
            if not input_text and not photo_id:
                await update.message.reply_text("❗ Текст или фото для рассылки.")
                return

            await update.message.reply_text("⏳ Начинаю рассылку...")
            count_success = 0
            count_fail = 0

            for uid in list(data["users"].keys()):
                try:
                    if photo_id:
                        await context.bot.send_photo(chat_id=uid, photo=photo_id, caption=input_text,
                                                     parse_mode="Markdown")
                    else:
                        await context.bot.send_message(chat_id=uid, text=input_text, parse_mode="Markdown")
                    count_success += 1
                except telegram.error.Forbidden:
                    count_fail += 1
                except Exception as e:
                    logger.warning(f"Не удалось отправить рассылку {uid}: {e}")
                    count_fail += 1
                await asyncio.sleep(0.05)

            result_message = (
                f"✅ **Рассылка завершена!**\n\n"
                f"📩 Отправлено: {count_success}\n"
                f"❌ Ошибок/Блок: {count_fail}"
            )

    # --- ЛИЧНОЕ СООБЩЕНИЕ ОТ ВЛАДЕЛЬЦА ---
    elif next_step == 'waiting_for_dm_message':
        target_id = context.user_data.get('dm_target_id')
        if not is_owner(user_id) or not target_id:
            result_message = "❌ Ошибка доступа или потерян контекст. Начните заново."
        elif not input_text and not photo_id:
            await update.message.reply_text("❗ Отправьте текст или фото для сообщения.")
            return
        else:
            target_data = data["users"].get(str(target_id), {})
            name = target_data.get("first_name") or "Без имени"
            username = target_data.get("username")
            recipient = f"{name} (@{username})" if username else name

            async def deliver(parse_mode: Optional[str]):
                """Отправляет сообщение получателю без звукового уведомления."""
                if photo_id:
                    return await context.bot.send_photo(
                        chat_id=target_id, photo=photo_id, caption=input_text or None,
                        parse_mode=parse_mode, disable_notification=True
                    )
                return await context.bot.send_message(
                    chat_id=target_id, text=input_text,
                    parse_mode=parse_mode, disable_notification=True
                )

            report_header = (
                f"👤 Получатель: {escape_md(recipient)}\n"
                f"🆔 ID: `{target_id}`\n"
            )

            try:
                try:
                    sent = await deliver("Markdown")
                except telegram.error.BadRequest:
                    # Если разметка некорректна — отправляем обычным текстом, чтобы сообщение не пропало
                    sent = await deliver(None)

                result_message = (
                    "✅ **Отчёт о доставке**\n\n"
                    + report_header +
                    f"📨 Статус: доставлено (без уведомления)\n"
                    f"🔢 ID сообщения: `{sent.message_id}`\n"
                    f"🕒 Время: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
                )
            except telegram.error.Forbidden:
                result_message = (
                    "❌ **Отчёт о доставке**\n\n"
                    + report_header +
                    "📨 Статус: не доставлено\n"
                    "ℹ️ Причина: пользователь заблокировал бота или не начинал с ним диалог."
                )
            except Exception as e:
                logger.error(f"Не удалось отправить личное сообщение {target_id}: {e}")
                result_message = (
                    "❌ **Отчёт о доставке**\n\n"
                    + report_header +
                    f"📨 Статус: не доставлено\n"
                    f"ℹ️ Причина: {escape_md(str(e))}"
                )

            context.user_data.pop('dm_target_id', None)

    # --- УПРАВЛЕНИЕ РЕАКЦИЯМИ ---
    elif next_step == 'waiting_for_react_group_name':
        if is_owner(user_id):
            new_group_name = input_text.split()[0].lower()
            if new_group_name in data.get("reaction_groups", {}):
                result_message = f"⚠️ Группа `{new_group_name}` уже существует."
            else:
                data["reaction_groups"][new_group_name] = ["👍"]
                save_data(data)
                result_message = f"✅ Группа **{new_group_name}** создана!"

    elif next_step == 'waiting_for_user_id_react_assign':
        if is_owner(user_id):
            try:
                target_id = int(input_text)
                context.user_data["reaction_context"] = {"target_user_id": target_id}

                result_message = f"👤 Выберите группу для пользователя `{target_id}`:"
                await update.message.reply_text(result_message, parse_mode="Markdown",
                                                reply_markup=get_reaction_groups_list_keyboard(data,
                                                                                               "assign_react_group"))
                return
            except ValueError:
                result_message = "❗ Введите корректный числовой ID."

    elif next_step.startswith('waiting_for_admin_id_'):
        if not is_owner(user_id):
            result_message = "❌ Только владелец."
        else:
            try:
                target_id = int(input_text)
                result_message = await process_add_admin(context,
                                                         target_id) if 'add' in next_step else await process_remove_admin(
                    context, target_id)
            except ValueError:
                await update.message.reply_text("❗ Введите число (ID).")
                return

    elif next_step.startswith('waiting_for_blacklist_'):
        if not is_owner(user_id):
            result_message = "❌ Только владелец."
        else:
            try:
                target_id = int(input_text)
                if 'add' in next_step:
                    result_message = await process_add_blacklist(context, target_id)
                else:
                    result_message = await process_remove_blacklist(context, target_id)
            except ValueError:
                await update.message.reply_text("❗ Введите число (ID).")
                return

    elif next_step.startswith('waiting_for_forward_'):
        if not is_owner(user_id):
            result_message = "❌ Только владелец."
        else:
            try:
                target_id = int(input_text)
                if 'add' in next_step:
                    result_message = await process_add_forward(context, target_id)
                else:
                    result_message = await process_remove_forward(context, target_id)
            except ValueError:
                await update.message.reply_text("❗ Введите число (ID).")
                return

    elif next_step.startswith('waiting_for_subject_'):
        if not is_admin(user_id, data):
            result_message = "❌ Нет прав."
        elif not input_text:
            await update.message.reply_text("❗ Введите название.")
            return
        else:
            result_message = await process_add_subject(context,
                                                       input_text) if 'add' in next_step else await process_remove_subject(
                context, input_text)

    # --- ДОБАВЛЕНИЕ/РЕДАКТИРОВАНИЕ ДЗ ---
    elif next_step in ['waiting_for_hw_task', 'waiting_for_edited_task']:
        hw_context = context.user_data.get('hw_context')
        if not is_admin(user_id, data) or not hw_context:
            result_message = "❌ Ошибка доступа."
        else:
            user_class_key = get_user_class_key(user_id, data)
            display_info = get_user_display_info(user_id, data)
            if not user_class_key:
                await update.message.reply_text("❌ Класс не определен.")
                return

            if not input_text and not photo_id:
                await update.message.reply_text("❗ Текст или фото.")
                return

            date_str, subject = hw_context['date'], hw_context['subject']
            action = hw_context.get('action', 'add')

            if user_class_key not in data["homework"]: data["homework"][user_class_key] = {}
            if date_str not in data["homework"][user_class_key]: data["homework"][user_class_key][date_str] = {}

            current_entry = data["homework"][user_class_key][date_str].get(subject, {})
            current_photos = get_hw_photos(current_entry)
            old_text = get_hw_text(current_entry)

            if photo_id and photo_id not in current_photos:
                current_photos.append(photo_id)

            if action == 'edit':
                display_text = input_text if input_text else old_text
            else:
                if old_text and input_text:
                    display_text = f"{old_text}\n{input_text}"
                elif input_text:
                    display_text = input_text
                else:
                    display_text = old_text

            if not display_text and not input_text:
                display_text = "См. фото 📸"

            entry = {"text": display_text, "photos": current_photos}

            data["homework"][user_class_key][date_str][subject] = entry
            save_data(data)

            safe_display_text = escape_md(display_text)
            safe_subject = escape_md(subject)

            count_photos = len(current_photos)
            photo_msg = f" (+{count_photos} фото)" if count_photos > 0 else ""
            result_message = f"🎉 **ДЗ ({escape_md(display_info)}) сохранено!**{photo_msg}\n{safe_subject}: {safe_display_text}"

    # --- ШАГ: ОЖИДАНИЕ ЗАГРУЗКИ ПОЛЕЗНОГО ФАЙЛА ---
    elif next_step == 'waiting_for_material_file':
        mat_context = context.user_data.get('material_context')
        if not is_admin(user_id, data) or not mat_context:
            result_message = "❌ Доступ ограничен."
        else:
            user_class_key = get_user_class_key(user_id, data)
            if not user_class_key:
                await update.message.reply_text("❌ Класс не определен.")
                return

            actual_file_id = document_id or photo_id
            actual_file_name = document_name or (f"Картинка_{random.randint(100, 999)}.jpg" if photo_id else None)

            if not actual_file_id:
                await update.message.reply_text("❗ Пожалуйста, отправьте именно **файл** (документ) или фото.")
                return

            context.user_data["material_context"]["file_id"] = actual_file_id
            context.user_data["material_context"]["file_name"] = actual_file_name

            context.user_data["next_step"] = "waiting_for_material_description"
            await update.message.reply_text(
                f"📎 Файл **{escape_md(actual_file_name)}** успешно принят!\n\n✏️ Теперь пришлите короткое **описание** к этому файлу (например, *«Формулы тригонометрии на контрольную»*):",
                parse_mode="Markdown"
            )
            return

    # --- ШАГ: ПОЛУЧЕНИЕ ОПИСАНИЯ ДЛЯ ФАЙЛА И СОХРАНЕНИЕ ---
    elif next_step == 'waiting_for_material_description':
        mat_context = context.user_data.get('material_context')
        if not is_admin(user_id, data) or not mat_context:
            result_message = "❌ Ошибка доступа."
        else:
            user_class_key = get_user_class_key(user_id, data)
            subject = mat_context.get("subject")
            file_id = mat_context.get("file_id")
            file_name = mat_context.get("file_name", "Файл")
            description = input_text if input_text else "Без описания"

            if not user_class_key or not subject or not file_id:
                await update.message.reply_text("❌ Ошибка контекста. Начните заново.")
                return

            if "materials" not in data:
                data["materials"] = {}
            if user_class_key not in data["materials"]:
                data["materials"][user_class_key] = {}
            if subject not in data["materials"][user_class_key]:
                data["materials"][user_class_key][subject] = []

            new_file_entry = {
                "name": file_name,
                "file_id": file_id,
                "description": description
            }
            data["materials"][user_class_key][subject].append(new_file_entry)
            save_data(data)

            result_message = f"🎉 **Учебный материал сохранён!**\n\n📚 Предмет: *{escape_md(subject)}*\n📄 Имя: *{escape_md(file_name)}*\n✏️ Памятка: _{escape_md(description)}_"

    if result_message:
        if not is_media_group:
            if 'hw_context' in context.user_data: del context.user_data['hw_context']
            if 'reaction_context' in context.user_data: del context.user_data['reaction_context']
            if 'material_context' in context.user_data: del context.user_data['material_context']
            if 'next_step' in context.user_data: del context.user_data['next_step']
            await update.message.reply_text(result_message, parse_mode="Markdown")
            await update.message.reply_text("Главное меню:", reply_markup=get_menu_keyboard(user_id, load_data()))


# --- ОТОБРАЖЕНИЕ ---
def get_display_weeks() -> List[datetime.date]:
    today = datetime.date.today()
    start = get_week_start(today)
    return [start + datetime.timedelta(days=i) for i in range(14)]


def format_hw_for_display(hw_data: Dict[str, Any], schedule_data: Dict[str, List[str]], date_list: List[datetime.date],
                          user_class_display: str) -> str:
    day_map = {
        "Monday": "Понедельник", "Tuesday": "Вторник", "Wednesday": "Среда", "Thursday": "Четверг",
        "Friday": "Пятница", "Saturday": "Суббота", "Sunday": "Воскресенье"
    }

    output = ""
    found_hw = False
    last_monday = None

    for date in date_list:
        date_str = date.strftime("%Y-%m-%d")
        day_of_week_en = date.strftime("%A")

        if date.weekday() == 0 and get_week_start(date) != last_monday:
            output += "===========================\n"
            output += f"**НЕДЕЛЯ С {date.strftime('%d.%m.%Y')}**\n"
            output += "===========================\n"
            last_monday = get_week_start(date)

        day_name = day_map.get(day_of_week_en)
        if date == datetime.date.today(): day_name = f"СЕГОДНЯ ({day_name})"

        scheduled_subjects = schedule_data.get(day_of_week_en, [])
        hw_subjects_today = hw_data.get(date_str, {})
        all_subjects = sorted(list(set(scheduled_subjects) | set(hw_subjects_today.keys())))

        if all_subjects:
            found_hw = True
            output += f"📅 **{day_name}, {date.strftime('%d.%m')}:**\n"

            for subject in all_subjects:
                safe_subject = escape_md(subject)

                if subject in hw_subjects_today:
                    entry = hw_subjects_today[subject]
                    text = escape_md(get_hw_text(entry))
                    photos = get_hw_photos(entry)
                    has_photo = f" 📸(x{len(photos)})" if photos else ""
                    output += f"    • **{safe_subject}:** {text}{has_photo}\n"
                else:
                    output += f"    • **{safe_subject}:** _Ничего не задано_\n"
            output += "\n"

    if not found_hw:
        return f"✨ **Расписания и заданий для {escape_md(user_class_display)} в этом периоде нет!**"

    return output


async def send_schedule_photos(context: ContextTypes.DEFAULT_TYPE, chat_id: int, hw_data: Dict[str, Any],
                               date_list: List[datetime.date]):
    if 'photo_msgs' not in context.user_data:
        context.user_data['photo_msgs'] = []

    for date in date_list:
        date_str = date.strftime("%Y-%m-%d")
        if date_str in hw_data:
            for subject, entry in hw_data[date_str].items():
                photos = get_hw_photos(entry)
                text = escape_md(get_hw_text(entry))
                safe_subject = escape_md(subject)

                if photos:
                    caption = f"📸 **{safe_subject}** ({date.strftime('%d.%m')})\n_{text}_"[:1024]

                    try:
                        if len(photos) == 1:
                            msg = await context.bot.send_photo(chat_id=chat_id, photo=photos[0], caption=caption,
                                                               parse_mode="Markdown")
                            context.user_data['photo_msgs'].append(msg.message_id)
                        else:
                            media_group = []
                            for i, p in enumerate(photos):
                                if i == 0:
                                    media_group.append(InputMediaPhoto(media=p, caption=caption, parse_mode="Markdown"))
                                else:
                                    media_group.append(InputMediaPhoto(media=p))

                            msgs = await context.bot.send_media_group(chat_id=chat_id, media=media_group)
                            for msg in msgs:
                                context.user_data['photo_msgs'].append(msg.message_id)

                        await asyncio.sleep(0.2)
                    except Exception as e:
                        logger.error(f"Ошибка при отправке фото ДЗ: {e}")


# --- ОБЕРТКИ КОМАНД ---
async def view_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = update.effective_user.id
    if is_blacklisted(user_id, data): return

    update_user_activity(user_id, data)
    save_data(data)

    user_class_key = get_user_class_key(user_id, data)
    display_info = get_user_display_info(user_id, data)

    if not user_class_key:
        await start_command(update, context)
        return

    dates = get_display_weeks()
    class_hw = data["homework"].get(user_class_key, {})
    class_schedule = data["schedule"].get(user_class_key, {})

    text = format_hw_for_display(class_hw, class_schedule, dates, display_info)
    await update.message.reply_text(text, parse_mode="Markdown")
    await send_schedule_photos(context, update.effective_chat.id, class_hw, dates)


# --- MAIN ---
def main():
    initial_data = load_data()
    save_data(initial_data)

    logger.info("Запуск бота...")

    proxy_url = os.getenv("TELEGRAM_PROXY")

    request_kwargs = {
        "connect_timeout": 20.0,
        "read_timeout": 20.0,
    }

    if proxy_url:
        request_kwargs["proxy_url"] = proxy_url
        logger.info(f"Используется прокси для Telegram: {proxy_url}")

    request_instance = HTTPXRequest(**request_kwargs)
    application = ApplicationBuilder().token(TOKEN).request(request_instance).build()

    private_filter = filters.ChatType.PRIVATE

    # Настройка команд бота
    application.add_handler(CommandHandler("start", start_command, filters=private_filter))
    application.add_handler(CommandHandler("menu", menu_command, filters=private_filter))
    application.add_handler(CommandHandler("help", help_command, filters=private_filter))
    application.add_handler(CommandHandler("view", view_command, filters=private_filter))
    application.add_handler(CommandHandler("ping", ping_command, filters=private_filter))
    application.add_handler(CommandHandler("cancel", cancel_command, filters=private_filter))
    application.add_handler(CommandHandler("ai", ai_command, filters=private_filter))  # Обработчик Groq AI

    application.add_handler(CallbackQueryHandler(button_callback))

    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND & private_filter,
            handle_message_input
        )
    )

    application.run_polling()


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()