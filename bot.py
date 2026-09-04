import subprocess
import sys

def install_if_missing(package):
    """Устанавливает пакет, если его нет."""
    try:
        __import__(package)
    except ImportError:
        print(f"⏳ Устанавливаю {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet"])

# Устанавливаем всё нужное ДО импортов
install_if_missing("telegram")
install_if_missing("telegram.ext")
install_if_missing("pypdf")
install_if_missing("PIL")
install_if_missing("dotenv")

print("✅ Все библиотеки на месте, запускаем бота...")

# ===== ДАЛЕЕ ИДУТ ВАШИ ОБЫЧНЫЕ ИМПОРТЫ =====
import uuid
import os
import shutil
import json
import logging
import asyncio
from enum import IntEnum
from typing import Set

from dotenv import load_dotenv
from PIL import Image
from pypdf import PdfReader, PdfWriter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
# ... и дальше весь ваш остальной код без изменений ...
import uuid
import os
import shutil
import json
import logging
import asyncio
import sys
from enum import IntEnum
from typing import Set

from dotenv import load_dotenv # Для загрузки переменных из .env файла
from PIL import Image
from pypdf import PdfReader, PdfWriter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# Загружаем переменные из файла .env (если он есть)
load_dotenv()

# ==================== ЛОГИРОВАНИЕ ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== НАСТРОЙКИ (БЕЗОПАСНЫЕ) ====================
# Берем из переменных окружения. Если их нет, подставится заглушка, которая вызовет ошибку при запуске (это правильно)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")

# ADMIN_IDS берем как строку "123, 456" и превращаем в список чисел [123, 456]
admin_ids_str = os.getenv("ADMIN_IDS", "123456789")
ADMIN_IDS = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip().isdigit()]

TEMP_DIR = "temp_images"
USERS_DB = "users.json"

# ⚠️ НАСТРОЙКА СКОРОСТИ РАССЫЛКИ (в секундах)
# 1.5 секунды = 40 сообщений в минуту. Это ОЧЕНЬ безопасно и практически исключает бан.
# Если хотите еще медленнее, поставьте 2.0 или 3.0
BROADCAST_DELAY_SECONDS = 1.5 


# ==================== СОСТОЯНИЯ ====================
class State(IntEnum):
    NONE = 0
    AWAITING_REORDER = 1
    AWAITING_BROADCAST = 2
    AWAITING_NAME = 3
    AWAITING_IMAGES_UPLOAD = 4
    AWAITING_MERGE_PDF1 = 5
    AWAITING_MERGE_PDF2 = 6
    AWAITING_DELETE_UPLOAD = 7
    AWAITING_DELETE_PAGES_INPUT = 8


# ==================== CALLBACK DATA ====================
class CB:
    CONVERT_IMAGES = "convert_images"
    MERGE_PDFS = "merge_pdfs"
    DELETE_PAGES = "delete_pages"
    SHOW_STATS = "show_stats"
    START_BROADCAST = "start_broadcast"
    BACK_MAIN = "back_main"
    CANCEL = "cancel"
    
    VIEW_IMAGES = "view_images"
    REORDER_IMAGES = "reorder_images"
    SET_NAME_CONVERT = "set_name_convert"
    DO_CONVERT = "do_convert"
    
    SET_NAME_MERGE = "set_name_merge"
    DO_MERGE = "do_merge"
    
    SET_NAME_DELETE = "set_name_delete"
    DO_DELETE_PAGES = "do_delete_pages"


# ==================== УТИЛИТЫ ====================
def load_users() -> Set[str]:
    if not os.path.exists(USERS_DB):
        return set()
    try:
        with open(USERS_DB, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception as e:
        logger.error(f"Ошибка загрузки пользователей: {e}")
        return set()


def save_users(users: Set[str]) -> None:
    try:
        with open(USERS_DB, "w", encoding="utf-8") as f:
            json.dump(list(users), f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Ошибка сохранения пользователей: {e}")


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def sanitize_filename(name: str) -> str:
    name = name.replace("/", "").replace("\\", "").replace("..", "").strip()
    return name or "file"


def get_pdf_filename(context: ContextTypes.DEFAULT_TYPE, default: str) -> str:
    return sanitize_filename(context.user_data.get("pdf_filename", default))


def safe_remove_file(file_path: str) -> None:
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            logger.warning(f"Не удалось удалить файл {file_path}: {e}")


def cleanup_user_dir(user_id: int) -> None:
    user_dir = os.path.join(TEMP_DIR, str(user_id))
    if os.path.exists(user_dir):
        shutil.rmtree(user_dir, ignore_errors=True)


def get_user_dir(user_id: int) -> str:
    user_dir = os.path.join(TEMP_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    return user_dir


# ==================== МЕНЮ ====================
def get_main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📄 Конвертировать изображения в PDF", callback_data=CB.CONVERT_IMAGES)],
        [InlineKeyboardButton("📎 Объединить несколько PDF файлов", callback_data=CB.MERGE_PDFS)],
        [InlineKeyboardButton("🗑 Удалить страницы из PDF файла", callback_data=CB.DELETE_PAGES)],
        [InlineKeyboardButton("📊 Статистика", callback_data=CB.SHOW_STATS)],
    ]
    if is_admin:
        keyboard.append([
            InlineKeyboardButton("📢 Рассылка", callback_data=CB.START_BROADCAST),
        ])
    return InlineKeyboardMarkup(keyboard)


def get_convert_submenu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📷 Просмотреть", callback_data=CB.VIEW_IMAGES),
            InlineKeyboardButton("🔄 Изменить порядок", callback_data=CB.REORDER_IMAGES),
        ],
        [InlineKeyboardButton("📝 Задать имя файла", callback_data=CB.SET_NAME_CONVERT)],
        [InlineKeyboardButton("✅ Конвертировать в PDF", callback_data=CB.DO_CONVERT)],
        [InlineKeyboardButton("️ Назад", callback_data=CB.BACK_MAIN)],
    ])


def get_merge_submenu(has_pdf1: bool = False, has_pdf2: bool = False) -> InlineKeyboardMarkup:
    keyboard = []
    if has_pdf1 and has_pdf2:
        keyboard.append([InlineKeyboardButton("📝 Задать имя файла", callback_data=CB.SET_NAME_MERGE)])
        keyboard.append([InlineKeyboardButton("✅ Объединить файлы", callback_data=CB.DO_MERGE)])
    elif has_pdf1:
        keyboard.append([InlineKeyboardButton("📤 Загрузите второй PDF файл", callback_data="hint_pdf2")])
    else:
        keyboard.append([InlineKeyboardButton(" Загрузите первый PDF файл", callback_data="hint_pdf1")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Назад в главное меню", callback_data=CB.BACK_MAIN)])
    return InlineKeyboardMarkup(keyboard)


def get_delete_submenu(has_pdf: bool = False) -> InlineKeyboardMarkup:
    keyboard = []
    if has_pdf:
        keyboard.append([InlineKeyboardButton(" Задать имя файла", callback_data=CB.SET_NAME_DELETE)])
        keyboard.append([InlineKeyboardButton("✅ Удалить страницы", callback_data=CB.DO_DELETE_PAGES)])
    else:
        keyboard.append([InlineKeyboardButton("📤 Загрузите PDF файл", callback_data="hint_pdf_del")])
    
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data=CB.BACK_MAIN)])
    return InlineKeyboardMarkup(keyboard)


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data=CB.CANCEL)]
    ])


# ==================== БАЗОВЫЕ ХЕНДЛЕРЫ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    users = load_users()

    if user_id not in users:
        users.add(user_id)
        save_users(users)
        logger.info(f"Новый пользователь: {user_id}")

    context.user_data["state"] = State.NONE
    admin = is_admin(update.message.from_user.id)

    await update.message.reply_text(
        f"Привет! Я бот для работы с PDF.\n"
        f"Вы один из {len(users)} пользователей.\n\n"
        "Выберите операцию:",
        reply_markup=get_main_menu(admin),
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    context.user_data["state"] = State.NONE
    context.user_data.pop("merge_pdf1", None)
    context.user_data.pop("merge_pdf2", None)
    context.user_data.pop("delete_pdf", None)
    context.user_data.pop("image_files", None)

    await query.message.reply_text(
        "❌ Операция отменена.",
        reply_markup=get_main_menu(is_admin(query.from_user.id))
    )


# ==================== ОБРАБОТКА МЕДИА ====================
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = context.user_data.get("state", State.NONE)
    
    if state != State.AWAITING_IMAGES_UPLOAD:
        await update.message.reply_text(
            "Сначала выберите 'Конвертировать изображения в PDF' в главном меню.",
            reply_markup=get_main_menu(is_admin(update.message.from_user.id))
        )
        return

    user_id = update.message.from_user.id
    user_dir = get_user_dir(user_id)

    if "image_files" not in context.user_data:
        context.user_data["image_files"] = []

    photo = update.message.photo[-1]
    file = await photo.get_file()
    ext = file.file_path.split(".")[-1].lower()

    if ext not in ["jpg", "jpeg", "png"]:
        await update.message.reply_text("Поддерживаются только JPG и PNG.")
        return

    file_name = f"{uuid.uuid4()}.{ext}"
    file_path = os.path.join(user_dir, file_name)
    await file.download_to_drive(file_path)

    context.user_data["image_files"].append(file_path)
    count = len(context.user_data['image_files'])
    logger.info(f"Пользователь {user_id} загрузил изображение №{count}")

    await update.message.reply_text(
        f"✅ Изображение загружено! (всего: {count})\n\n"
        f"Можете загрузить ещё или нажать 'Конвертировать в PDF'",
        reply_markup=get_convert_submenu(),
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document = update.message.document
    if not document.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("Пожалуйста, отправляйте только PDF-файлы.")
        return

    user_id = update.message.from_user.id
    user_dir = get_user_dir(user_id)
    state = context.user_data.get("state", State.NONE)

    file = await document.get_file()
    file_name = f"{uuid.uuid4()}.pdf"
    file_path = os.path.join(user_dir, file_name)
    await file.download_to_drive(file_path)

    if state == State.AWAITING_MERGE_PDF1:
        context.user_data["merge_pdf1"] = file_path
        context.user_data["state"] = State.AWAITING_MERGE_PDF2
        await update.message.reply_text(
            f"✅ Первый PDF загружен!\n\n"
            f" Файл: {document.file_name}\n\n"
            f"Теперь загрузите ВТОРОЙ PDF файл:",
            reply_markup=get_merge_submenu(has_pdf1=True, has_pdf2=False),
            parse_mode="Markdown"
        )
        return

    elif state == State.AWAITING_MERGE_PDF2:
        context.user_data["merge_pdf2"] = file_path
        await update.message.reply_text(
            f"✅ Второй PDF загружен!\n\n"
            f"📄 Файл: {document.file_name}\n\n"
            f"Оба файла готовы! Теперь можете:\n"
            f"• Задать имя файла\n"
            f"• Или сразу объединить",
            reply_markup=get_merge_submenu(has_pdf1=True, has_pdf2=True),
            parse_mode="Markdown"
        )
        return

    if state == State.AWAITING_DELETE_UPLOAD:
        context.user_data["delete_pdf"] = file_path
        context.user_data["state"] = State.AWAITING_DELETE_PAGES_INPUT
        await update.message.reply_text(
            f"✅ PDF загружен!\n\n"
            f"📄 Файл: {document.file_name}\n\n"
            f"Теперь:\n"
            f"1️⃣ Введите номера страниц для удаления (через пробел)\n"
            f"   Пример: 1 3 5\n"
            f"2️⃣ Или задайте имя файла\n"
            f"3️⃣ Или нажмите 'Удалить страницы'",
            reply_markup=get_delete_submenu(has_pdf=True),
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        "Выберите операцию в главном меню:",
        reply_markup=get_main_menu(is_admin(user_id))
    )


# ==================== ОБРАБОТКА КНОПОК ====================
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    admin = is_admin(user_id)

    if data == CB.CONVERT_IMAGES:
        context.user_data["state"] = State.AWAITING_IMAGES_UPLOAD
        context.user_data["image_files"] = []
        await query.message.reply_text(
            "📄 **Конвертация изображений в PDF**\n\n"
            "Отправьте изображения (JPG или PNG).\n"
            "Можно несколько файлов.",
            reply_markup=get_convert_submenu(),
            parse_mode="Markdown"
        )

    elif data == CB.MERGE_PDFS:
        context.user_data["state"] = State.AWAITING_MERGE_PDF1
        context.user_data.pop("merge_pdf1", None)
        context.user_data.pop("merge_pdf2", None)
        await query.message.reply_text(
            "📎 **Объединение PDF файлов**\n\n"
            "Загрузите ПЕРВЫЙ PDF файл:",
            reply_markup=get_merge_submenu(has_pdf1=False, has_pdf2=False),
            parse_mode="Markdown"
        )

    elif data == CB.DELETE_PAGES:
        context.user_data["state"] = State.AWAITING_DELETE_UPLOAD
        context.user_data.pop("delete_pdf", None)
        await query.message.reply_text(
            "🗑 **Удаление страниц из PDF**\n\n"
            "Загрузите PDF файл:",
            reply_markup=get_delete_submenu(has_pdf=False),
            parse_mode="Markdown"
        )

    elif data == CB.SHOW_STATS:
        await show_stats(update, context)

    elif data == CB.START_BROADCAST:
        if admin:
            await start_broadcast(update, context)
        else:
            await query.message.reply_text("Только для администратора.")

    elif data == CB.BACK_MAIN:
        context.user_data["state"] = State.NONE
        context.user_data.pop("image_files", None)
        context.user_data.pop("merge_pdf1", None)
        context.user_data.pop("merge_pdf2", None)
        context.user_data.pop("delete_pdf", None)
        await query.message.reply_text(
            "📋 Главное меню:",
            reply_markup=get_main_menu(admin)
        )

    elif data == CB.CANCEL:
        await cancel(update, context)

    elif data == CB.VIEW_IMAGES:
        await view_images(update, context)

    elif data == CB.REORDER_IMAGES:
        await prompt_reorder_images(update, context)

    elif data == CB.SET_NAME_CONVERT:
        current_name = get_pdf_filename(context, "output")
        context.user_data["state"] = State.AWAITING_NAME
        context.user_data["name_for"] = "convert"
        await query.message.reply_text(
            f"📝 Введите имя для PDF (без .pdf)\n\n"
            f"Текущее: `{current_name}`",
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown"
        )

    elif data == CB.DO_CONVERT:
        await convert_to_pdf(update, context)

    elif data == CB.SET_NAME_MERGE:
        context.user_data["state"] = State.AWAITING_NAME
        context.user_data["name_for"] = "merge"
        await query.message.reply_text(
            " Введите имя для объединённого PDF (без .pdf):",
            reply_markup=get_cancel_keyboard()
        )

    elif data == CB.DO_MERGE:
        await merge_two_pdfs(update, context)

    elif data == CB.SET_NAME_DELETE:
        context.user_data["state"] = State.AWAITING_NAME
        context.user_data["name_for"] = "delete"
        await query.message.reply_text(
            "📝 Введите имя для PDF (без .pdf):",
            reply_markup=get_cancel_keyboard()
        )

    elif data == CB.DO_DELETE_PAGES:
        if "delete_pdf" not in context.user_data:
            await query.message.reply_text("❌ Сначала загрузите PDF файл!", reply_markup=get_delete_submenu(has_pdf=False))
            return
        if "pages_to_delete" not in context.user_data:
            await query.message.reply_text("❌ Сначала введите номера страниц для удаления!\n\nПример: 1 3 5", reply_markup=get_delete_submenu(has_pdf=True))
            return
        await process_delete_pages(update, context, context.user_data["pages_to_delete"])


# ==================== ОПЕРАЦИИ С ИЗОБРАЖЕНИЯМИ ====================
async def view_images(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if "image_files" not in context.user_data or not context.user_data["image_files"]:
        await query.message.reply_text("❌ Вы ещё не загрузили изображения!", reply_markup=get_convert_submenu())
        return

    image_files = context.user_data["image_files"]
    message = "📷 **Загруженные изображения:**\n\n" + "\n".join(
        f"{i + 1}. {os.path.basename(f)}" for i, f in enumerate(image_files)
    )
    await query.message.reply_text(message, reply_markup=get_convert_submenu(), parse_mode="Markdown")


async def prompt_reorder_images(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if "image_files" not in context.user_data or not context.user_data["image_files"]:
        await query.message.reply_text("❌ Вы ещё не загрузили изображения!", reply_markup=get_convert_submenu())
        return

    image_files = context.user_data["image_files"]
    message = "🔄 **Текущий порядок:**\n\n" + "\n".join(
        f"{i + 1}. {os.path.basename(f)}" for i, f in enumerate(image_files)
    )
    message += "\n\n📝 Введите новые номера через пробел.\nПример: `2 1 3`"

    context.user_data["state"] = State.AWAITING_REORDER
    await query.message.reply_text(message, reply_markup=get_cancel_keyboard(), parse_mode="Markdown")


# ==================== ОПЕРАЦИИ С PDF ====================
async def convert_to_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if "image_files" not in context.user_data or not context.user_data["image_files"]:
        await query.message.reply_text("❌ Нет загруженных изображений!", reply_markup=get_main_menu(is_admin(user_id)))
        return

    image_files = [f for f in context.user_data["image_files"] if os.path.exists(f)]
    if not image_files:
        await query.message.reply_text("❌ Нет валидных изображений.", reply_markup=get_main_menu(is_admin(user_id)))
        return

    user_dir = get_user_dir(user_id)
    filename = get_pdf_filename(context, f"output_{user_id}") + ".pdf"
    pdf_path = os.path.join(user_dir, filename)

    try:
        images = [Image.open(f).convert("RGB") for f in image_files]
        images[0].save(pdf_path, "PDF", resolution=100.0, save_all=True, append_images=images[1:])
        logger.info(f"Создан PDF для пользователя {user_id}: {filename}")
    except Exception as e:
        logger.error(f"Ошибка создания PDF: {e}")
        await query.message.reply_text(f"❌ Ошибка создания PDF: {e}", reply_markup=get_main_menu(is_admin(user_id)))
        return

    with open(pdf_path, "rb") as pdf_file:
        await query.message.reply_document(document=pdf_file, filename=filename, caption="✅ PDF создан!")

    cleanup_user_dir(user_id)
    context.user_data.pop("image_files", None)
    context.user_data["state"] = State.NONE
    await query.message.reply_text("PDF отправлен! Выберите операцию:", reply_markup=get_main_menu(is_admin(user_id)))


async def merge_two_pdfs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query if update.callback_query else None
    msg = query.message if query else update.message
    
    pdf1 = context.user_data.get("merge_pdf1")
    pdf2 = context.user_data.get("merge_pdf2")

    if not pdf1 or not pdf2:
        await msg.reply_text("❌ Загрузите оба PDF файла!")
        return

    user_id = update.message.from_user.id if update.message else query.from_user.id
    user_dir = get_user_dir(user_id)
    filename = get_pdf_filename(context, "merged") + ".pdf"
    output_path = os.path.join(user_dir, filename)

    try:
        writer = PdfWriter()
        for path in [pdf1, pdf2]:
            reader = PdfReader(path)
            for page in reader.pages:
                writer.add_page(page)

        with open(output_path, "wb") as f:
            writer.write(f)

        with open(output_path, "rb") as f:
            reply_doc = msg.reply_document if hasattr(msg, 'reply_document') else msg.reply_text
            await reply_doc(document=InputFile(f, filename=filename), caption="✅ PDF успешно объединены!")
        logger.info(f"Объединены PDF для пользователя {user_id}")
    except Exception as e:
        logger.error(f"Ошибка при объединении PDF: {e}")
        await msg.reply_text(f"❌ Ошибка при объединении: {e}")
    finally:
        for p in [pdf1, pdf2, output_path]:
            safe_remove_file(p)
        context.user_data.pop("merge_pdf1", None)
        context.user_data.pop("merge_pdf2", None)
        context.user_data["state"] = State.NONE

    reply_text = msg.reply_text if hasattr(msg, 'reply_text') else msg.reply_text
    await reply_text("Готово! Выберите операцию:", reply_markup=get_main_menu(is_admin(user_id)))


async def process_delete_pages(update: Update, context: ContextTypes.DEFAULT_TYPE, pages_text: str) -> None:
    query = update.callback_query if update.callback_query else None
    msg = query.message if query else update.message
    
    pdf_path = context.user_data.get("delete_pdf")
    if not pdf_path or not os.path.exists(pdf_path):
        await msg.reply_text("❌ PDF не найден. Начните заново.")
        context.user_data["state"] = State.NONE
        return

    try:
        pages_to_delete = {int(p) - 1 for p in pages_text.split()}
    except ValueError:
        await msg.reply_text("❌ Неверный формат. Введите номера через пробел: `1 3 5`", reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
        return

    user_id = update.message.from_user.id if update.message else query.from_user.id
    user_dir = get_user_dir(user_id)
    filename = get_pdf_filename(context, "cleaned") + ".pdf"
    output_path = os.path.join(user_dir, filename)

    try:
        reader = PdfReader(pdf_path)
        writer = PdfWriter()
        total = len(reader.pages)

        for i in range(total):
            if i not in pages_to_delete:
                writer.add_page(reader.pages[i])

        if len(writer.pages) == 0:
            await msg.reply_text("❌ После удаления не осталось страниц!")
            return

        with open(output_path, "wb") as f:
            writer.write(f)

        with open(output_path, "rb") as f:
            await msg.reply_document(document=InputFile(f, filename=filename), caption=f"✅ Удалены страницы: {pages_text}\nОсталось: {len(writer.pages)}")
        logger.info(f"Удалены страницы из PDF для пользователя {user_id}: {pages_text}")
    except Exception as e:
        logger.error(f"Ошибка удаления страниц: {e}")
        await msg.reply_text(f"❌ Ошибка: {e}")
    finally:
        for p in [pdf_path, output_path]:
            safe_remove_file(p)
        context.user_data.pop("delete_pdf", None)
        context.user_data.pop("pages_to_delete", None)
        context.user_data["state"] = State.NONE

    await msg.reply_text("Готово! Выберите операцию:", reply_markup=get_main_menu(is_admin(user_id)))


# ==================== АДМИН ФУНКЦИИ ====================
async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    context.user_data["state"] = State.AWAITING_BROADCAST
    await query.message.reply_text(
        "📢 Введите текст рассылки:\n\n"
        "⚠️ *Примечание:* Рассылка будет идти медленно (с паузами), чтобы Telegram не заблокировал бота за спам. Пожалуйста, подождите.",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )


async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    users = load_users()
    success = fail = 0
    total = len(users)

    if total == 0:
        await update.message.reply_text("❌ В базе нет пользователей для рассылки.")
        context.user_data["state"] = State.NONE
        return

    status_msg = await update.message.reply_text(f"📢 Начинаю медленную рассылку на {total} пользователей...\nЭто может занять время.")

    for index, uid in enumerate(users):
        try:
            await context.bot.send_message(chat_id=int(uid), text=text, parse_mode="Markdown")
            success += 1
        except Exception as e:
            logger.warning(f"Ошибка отправки пользователю {uid}: {e}")
            fail += 1
        
        # ⚠️ ГЛАВНАЯ ЗАЩИТА ОТ БАНА: Пауза между каждым сообщением
        if index < total - 1:
            await asyncio.sleep(BROADCAST_DELAY_SECONDS)
            
        # Обновляем статус каждые 10 сообщений, чтобы вы видели прогресс
        if (index + 1) % 10 == 0 or (index + 1) == total:
            try:
                await status_msg.edit_text(
                    f"📢 Идет рассылка...\n"
                    f"Обработано: {index + 1} из {total}\n"
                    f"✅ Успешно: {success}\n"
                    f"❌ Ошибок (заблокировали бота): {fail}"
                )
            except Exception:
                pass # Игнорируем ошибки редактирования, чтобы не прервать цикл

    await status_msg.edit_text(
        f"✅ Рассылка полностью завершена!\n\n"
        f"👥 Всего в базе: {total}\n"
        f"✅ Доставлено: {success}\n"
        f"❌ Ошибок: {fail}"
    )
    
    context.user_data["state"] = State.NONE
    await update.message.reply_text("Главное меню:", reply_markup=get_main_menu(True))


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    users = load_users()
    await update.callback_query.message.reply_text(
        f"📊 Всего пользователей: {len(users)}",
        reply_markup=get_main_menu(is_admin(update.callback_query.from_user.id))
    )


# ==================== ТЕКСТОВЫЙ ВВОД ====================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    state = context.user_data.get("state", State.NONE)
    user_id = update.message.from_user.id

    if state == State.AWAITING_NAME:
        name = sanitize_filename(text)
        if not name:
            await update.message.reply_text("❌ Имя не может быть пустым.")
            return

        context.user_data["pdf_filename"] = name
        context.user_data["state"] = State.NONE
        name_for = context.user_data.pop("name_for", None)

        if name_for == "convert":
            menu = get_convert_submenu()
            op = "конвертации"
        elif name_for == "merge":
            menu = get_merge_submenu(has_pdf1="merge_pdf1" in context.user_data, has_pdf2="merge_pdf2" in context.user_data)
            op = "объединения"
        elif name_for == "delete":
            menu = get_delete_submenu(has_pdf="delete_pdf" in context.user_data)
            op = "удаления страниц"
        else:
            menu = get_main_menu(is_admin(user_id))
            op = "работы"

        await update.message.reply_text(f"✅ Имя установлено: `{name}.pdf`\n\nПродолжите {op}.", reply_markup=menu, parse_mode="Markdown")
        return

    if state == State.AWAITING_REORDER:
        image_files = context.user_data.get("image_files", [])
        if not image_files:
            context.user_data["state"] = State.NONE
            await update.message.reply_text("❌ Нет изображений.", reply_markup=get_main_menu(is_admin(user_id)))
            return
        try:
            new_order = [int(i) - 1 for i in text.split()]
            num = len(image_files)
            if len(new_order) != num or len(set(new_order)) != num or any(i < 0 or i >= num for i in new_order):
                raise ValueError(f"Нужно {num} уникальных чисел от 1 до {num}")
            context.user_data["image_files"] = [image_files[i] for i in new_order]
            msg = "🔄 Новый порядок:\n\n" + "\n".join(f"{i+1}. {os.path.basename(f)}" for i, f in enumerate(context.user_data["image_files"]))
            context.user_data["state"] = State.AWAITING_IMAGES_UPLOAD
            await update.message.reply_text(msg, reply_markup=get_convert_submenu(), parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")

    elif state == State.AWAITING_BROADCAST:
        if is_admin(user_id):
            await do_broadcast(update, context, text)
        else:
            context.user_data["state"] = State.NONE
            await update.message.reply_text("Нет доступа.")

    elif state == State.AWAITING_DELETE_PAGES_INPUT:
        try:
            pages = [int(p) for p in text.split()]
            if not pages:
                raise ValueError()
            context.user_data["pages_to_delete"] = text
            context.user_data["state"] = State.AWAITING_DELETE_UPLOAD
            
            await update.message.reply_text(
                f"✅ Номера страниц сохранены: {text}\n\n"
                f"Теперь нажмите 'Удалить страницы' или задайте имя файла:",
                reply_markup=get_delete_submenu(has_pdf=True),
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ Введите корректные номера страниц через пробел.\nПример: `1 3 5`", parse_mode="Markdown")

    else:
        await update.message.reply_text("Выберите операцию в главном меню:", reply_markup=get_main_menu(is_admin(user_id)))


# ==================== ЗАПУСК ====================
def main() -> None:
    os.makedirs(TEMP_DIR, exist_ok=True)

    # Строгая проверка токена
    if not TOKEN or TOKEN == "ВАШ_ТОКЕН_ЗДЕСЬ":
        logger.error("❌ ОШИБКА: Токен не установлен!")
        logger.error("Создайте файл .env и добавьте туда строку: TELEGRAM_BOT_TOKEN=ваш_токен")
        sys.exit(1)

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(CallbackQueryHandler(handle_button))
    application.add_handler(CallbackQueryHandler(cancel, pattern=f"^{CB.CANCEL}$"))

    logger.info("✅ Бот успешно запущен!")
    application.run_polling()


if __name__ == "__main__":
    main()
