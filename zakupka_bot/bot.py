"""Telegram-бот «Закупка в поездку».

Запуск:  BOT_TOKEN=123:abc python bot.py
Подробности в README.md.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from telegram import BotCommand, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import core
import ui

log = logging.getLogger("zakupka")

# Для этих вопросов подсказываем, что «-» очищает поле.
CLEARABLE = {"f_per", "f_size", "f_price", "x_sum", "dish_por", "title"}


# ---------------------------------------------------------------------------
# Хранилище: по одному JSON-файлу на чат
# ---------------------------------------------------------------------------
class Store:
    def __init__(self, folder: str):
        self.dir = Path(folder)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cache: dict[int, dict] = {}

    def _path(self, chat_id: int) -> Path:
        return self.dir / f"{chat_id}.json"

    def get(self, chat_id: int) -> dict:
        if chat_id in self.cache:
            return self.cache[chat_id]
        S = None
        p = self._path(chat_id)
        if p.exists():
            try:
                S = json.loads(p.read_text("utf-8"))
            except (OSError, ValueError):
                log.exception("Не удалось прочитать %s, начинаю с чистого листа", p)
        if not isinstance(S, dict):
            S = core.blank_state()
        for k, v in core.blank_state().items():
            S.setdefault(k, v)
        self.cache[chat_id] = S
        return S

    def save(self, chat_id: int) -> None:
        p = self._path(chat_id)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache[chat_id], ensure_ascii=False), "utf-8")
        os.replace(tmp, p)


store: Store | None = None
ALLOWED: set[int] = set()


def allowed(chat_id: int) -> bool:
    return not ALLOWED or chat_id in ALLOWED


# ---------------------------------------------------------------------------
# Вспомогательные функции Telegram
# ---------------------------------------------------------------------------
def markup(kb: ui.Kb) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in kb])


def clip(text: str) -> str:
    if len(text) <= 4000:
        return text
    return text[:3990].rsplit("\n", 1)[0] + "\n…"


def user_of(u) -> dict:
    return {"id": u.id, "name": u.first_name or u.username or "Участник"}


async def send_panel(bot, chat_id: int, screen: ui.Screen) -> None:
    text, kb = screen
    await bot.send_message(chat_id, clip(text), reply_markup=markup(kb), parse_mode=ParseMode.HTML)


async def edit_panel(bot, chat_id: int, message_id: int, screen: ui.Screen) -> None:
    text, kb = screen
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=clip(text),
            reply_markup=markup(kb), parse_mode=ParseMode.HTML)
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
        # Сообщение могло быть удалено или слишком старое: покажем экран новым сообщением.
        log.warning("Не получилось изменить сообщение: %s", e)
        await send_panel(bot, chat_id, screen)


async def safe_delete(bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramError:
        pass  # в группе без прав администратора удалить чужое сообщение нельзя


async def send_ask(bot, S: dict, chat_id: int, panel_id: int, ask: ui.Ask, user: dict, private: bool) -> None:
    mention = "" if private else f'<a href="tg://user?id={user["id"]}">{ui.h(user["name"])}</a>, '
    hint = "\n<i>Ответьте на это сообщение. «-» очищает поле.</i>" if ask.meta["kind"] in CLEARABLE else \
        "\n<i>Ответьте на это сообщение.</i>"
    kwargs = {"selective": True}
    if ask.placeholder:
        kwargs["input_field_placeholder"] = ask.placeholder[:64]
    msg = await bot.send_message(
        chat_id, mention + ask.text + hint, parse_mode=ParseMode.HTML, reply_markup=ForceReply(**kwargs))
    S["prompts"][str(msg.message_id)] = {**ask.meta, "panel": [chat_id, panel_id]}
    while len(S["prompts"]) > 40:
        S["prompts"].pop(next(iter(S["prompts"])))
    store.save(chat_id)


async def send_export(bot, S: dict, chat_id: int) -> None:
    data = json.dumps(core.export_state(S), ensure_ascii=False, indent=1).encode("utf-8")
    await bot.send_document(
        chat_id, document=data, filename="zakupka.json",
        caption="Данные закупки. Чтобы загрузить обратно: Ещё → Импорт. Файл подходит и для веб-калькулятора.")


async def apply_out(bot, S: dict, chat_id: int, panel_id: int, out: ui.Out, user: dict, private: bool) -> None:
    if out.screen:
        await edit_panel(bot, chat_id, panel_id, out.screen)
    if out.ask:
        await send_ask(bot, S, chat_id, panel_id, out.ask, user, private)
    if out.send:
        await bot.send_message(chat_id, clip(out.send), parse_mode=ParseMode.HTML)
    if out.export:
        await send_export(bot, S, chat_id)


# ---------------------------------------------------------------------------
# Обработчики
# ---------------------------------------------------------------------------
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    msg = q.message
    if msg is None or not allowed(msg.chat_id):
        await q.answer()
        return
    chat_id = msg.chat_id
    S = store.get(chat_id)
    user = user_of(q.from_user)
    try:
        out = ui.act(S, (q.data or "").split(":"), user)
    except Exception:  # noqa: BLE001 - не роняем бота из-за одной кнопки
        log.exception("Ошибка в действии %s", q.data)
        await q.answer("Что-то пошло не так. Откройте /menu")
        return
    store.save(chat_id)
    await q.answer(out.toast or None)
    await apply_out(context.bot, S, chat_id, msg.message_id, out, user, msg.chat.type == "private")


async def on_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    m = update.message
    if m is None or m.reply_to_message is None or not m.text or not allowed(m.chat_id):
        return
    chat_id = m.chat_id
    S = store.get(chat_id)
    key = str(m.reply_to_message.message_id)
    pr = S["prompts"].get(key)
    if pr is None:
        return
    if pr["kind"] == "import":
        await m.reply_text("Для импорта пришлите файл .json, а не текст.")
        return
    out = ui.reply(S, pr, m.text)
    if out.err:
        await m.reply_text("⚠️ " + out.err + "\nОтветьте ещё раз на сообщение с вопросом.")
        return
    S["prompts"].pop(key, None)
    store.save(chat_id)
    await safe_delete(context.bot, chat_id, m.message_id)
    await safe_delete(context.bot, chat_id, m.reply_to_message.message_id)
    await apply_out(context.bot, S, chat_id, pr["panel"][1], out, user_of(m.from_user), m.chat.type == "private")


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    m = update.message
    if m is None or m.document is None or not allowed(m.chat_id):
        return
    chat_id = m.chat_id
    S = store.get(chat_id)
    key = str(m.reply_to_message.message_id) if m.reply_to_message else None
    pr = S["prompts"].get(key) if key else None
    wants = (pr is not None and pr["kind"] == "import") or (m.caption or "").strip().lower().startswith("/import")
    if not wants:
        return
    if (m.document.file_size or 0) > 1_000_000:
        await m.reply_text("Файл слишком большой для импорта.")
        return
    try:
        f = await m.document.get_file()
        data = bytes(await f.download_as_bytearray())
        new = core.sanitize(json.loads(data.decode("utf-8")))
    except Exception:  # noqa: BLE001
        log.exception("Импорт не удался")
        await m.reply_text("Не получилось прочитать файл. Нужен файл, который бот или веб-калькулятор сохранил через «Экспорт».")
        return
    ui.replace_state(S, new)
    store.save(chat_id)
    if key:
        await safe_delete(context.bot, chat_id, m.reply_to_message.message_id)
    await m.reply_text("✅ Данные загружены.")
    await send_panel(context.bot, chat_id, ui.scr_menu(S))


def _screen_command(builder):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        m = update.effective_message
        if m is None or not allowed(m.chat_id):
            return
        await send_panel(context.bot, m.chat_id, builder(store.get(m.chat_id)))
    return handler


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    m = update.effective_message
    if m is not None and allowed(m.chat_id):
        await send_panel(context.bot, m.chat_id, (ui.HELP, [[ui.B("🏕 Открыть меню", "m")]]))


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    m = update.effective_message
    if m is not None and allowed(m.chat_id):
        await send_export(context.bot, store.get(m.chat_id), m.chat_id)


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("menu", "Главное меню"),
        BotCommand("shop", "Список покупок"),
        BotCommand("settle", "Расчёт: кто кому переводит"),
        BotCommand("export", "Файл с данными"),
        BotCommand("help", "Как пользоваться"),
    ])


def load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text("utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> None:
    global store, ALLOWED
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    load_dotenv()
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Задайте токен бота: BOT_TOKEN=... python bot.py (токен выдаёт @BotFather)")
    store = Store(os.environ.get("DATA_DIR", "data"))
    ALLOWED = {int(x) for x in os.environ.get("ALLOWED_CHATS", "").replace(" ", "").split(",") if x}

    app = Application.builder().token(token).post_init(post_init).build()
    app.add_handler(CommandHandler(["start", "menu"], _screen_command(ui.scr_menu)))
    app.add_handler(CommandHandler("shop", _screen_command(lambda S: ui.scr_shop(S, 0))))
    app.add_handler(CommandHandler("settle", _screen_command(ui.scr_settle)))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.REPLY, on_reply))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
