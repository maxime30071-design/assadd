import uuid
import os
import shutil
import json
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# Токен вашего бота (замените на свой)
TOKEN = "7832050685:AAHGknh0xhzkbP7S3Ur0LWAnDtTG-lRVYZk"

# Папка для временного хранения изображений
TEMP_DIR = "temp_images"

# Файл для хранения пользователей
USERS_DB = "users.json"

# Состояния для обработки ввода
STATE_NONE = 0
STATE_AWAITING_PDF_NAME = 1
STATE_AWAITING_REORDER = 2

def get_main_menu():
    """Создаёт основное меню с кнопками."""
    keyboard = [
        [
            InlineKeyboardButton("📷 Просмотреть изображения", callback_data="view_images"),
            InlineKeyboardButton("📝 Задать имя PDF", callback_data="set_pdf_name"),
        ],
        [
            InlineKeyboardButton("🔄 Изменить порядок", callback_data="reorder_images"),
            InlineKeyboardButton("📄 Конвертировать в PDF", callback_data="convert_to_pdf"),
        ],
        [
            InlineKeyboardButton("📊 Статистика", callback_data="show_stats"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def load_users():
    """Загружает список пользователей из файла."""
    if not os.path.exists(USERS_DB):
        return set()
    with open(USERS_DB, "r") as f:
        data = json.load(f)
    return set(data)

def save_users(users):
    """Сохраняет список пользователей в файл."""
    with open(USERS_DB, "w") as f:
        json.dump(list(users), f)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start: показывает приветственное сообщение и меню."""
    user_id = str(update.message.from_user.id)
    users = load_users()
    # Добавляем нового пользователя, если его нет в списке
    if user_id not in users:
        users.add(user_id)
        save_users(users)
    context.user_data['state'] = STATE_NONE
    await update.message.reply_text(
        f"Привет! Я бот для создания PDF из изображений.\n"
        f"Вы один из {len(users)} пользователей этого бота.\n\n"
        "1. Отправляй изображения (JPG, PNG).\n"
        "2. Используй кнопки ниже для управления.\n"
        "3. Нажми 'Конвертировать в PDF', когда будешь готов.",
        reply_markup=get_main_menu(),
    )

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик получения изображений."""
    user_id = update.message.from_user.id
    user_dir = os.path.join(TEMP_DIR, str(user_id))
    # Создаём папку для пользователя, если её нет
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    # Инициализируем список для хранения порядка изображений
    if 'image_files' not in context.user_data:
        context.user_data['image_files'] = []
    # Получаем файл изображения
    photo = update.message.photo[-1]  # Берём изображение наивысшего качества
    file = await photo.get_file()
    file_extension = file.file_path.split('.')[-1].lower()
    # Проверяем, что это поддерживаемый формат
    if file_extension not in ['jpg', 'jpeg', 'png']:
        await update.message.reply_text("Пожалуйста, отправляйте только JPG или PNG изображения.")
        return
    # Генерируем уникальное имя файла
    file_name = f"{uuid.uuid4()}.{file_extension}"
    file_path = os.path.join(user_dir, file_name)
    # Скачиваем изображение
    await file.download_to_drive(file_path)
    # Добавляем путь к файлу в список
    context.user_data['image_files'].append(file_path)
    await update.message.reply_text(
        f"Изображение получено (№{len(context.user_data['image_files'])})! "
        "Отправьте ещё или используйте меню.",
        reply_markup=get_main_menu(),
    )

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки."""
    query = update.callback_query
    await query.answer()
    if query.data == "view_images":
        await view_images(update, context)
    elif query.data == "set_pdf_name":
        await prompt_set_pdf_name(update, context)
    elif query.data == "reorder_images":
        await prompt_reorder_images(update, context)
    elif query.data == "convert_to_pdf":
        await convert_to_pdf(update, context)
    elif query.data == "show_stats":
        await show_stats(update, context)

async def view_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список загруженных изображений."""
    query = update.callback_query
    if 'image_files' not in context.user_data or not context.user_data['image_files']:
        await query.message.reply_text(
            "Вы ещё не загрузили изображения!",
            reply_markup=get_main_menu()
        )
        return
    image_files = context.user_data['image_files']
    message = "Загруженные изображения:\n" + "\n".join(
        f"{i + 1}. {os.path.basename(f)}" for i, f in enumerate(image_files)
    )
    await query.message.reply_text(message, reply_markup=get_main_menu())

async def prompt_set_pdf_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрашивает имя PDF."""
    query = update.callback_query
    context.user_data['state'] = STATE_AWAITING_PDF_NAME
    await query.message.reply_text(
        "Введите имя для PDF-файла (например, мой_документ):",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Отмена", callback_data="cancel")
        ]])
    )

async def prompt_reorder_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрашивает новый порядок изображений."""
    query = update.callback_query
    if 'image_files' not in context.user_data or not context.user_data['image_files']:
        await query.message.reply_text(
            "Вы ещё не загрузили изображения!",
            reply_markup=get_main_menu()
        )
        return
    image_files = context.user_data['image_files']
    message = "Текущий порядок изображений:\n" + "\n".join(
        f"{i + 1}. {os.path.basename(f)}" for i, f in enumerate(image_files)
    )
    message += "\nВведите индексы через пробел для нового порядка, например: 2 1 3"
    context.user_data['state'] = STATE_AWAITING_REORDER
    await query.message.reply_text(
        message,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Отмена", callback_data="cancel")
        ]])
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет текущую операцию."""
    query = update.callback_query
    context.user_data['state'] = STATE_NONE
    await query.message.reply_text(
        "Операция отменена.",
        reply_markup=get_main_menu()
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовый ввод для имени PDF или порядка изображений."""
    text = update.message.text.strip()
    state = context.user_data.get('state', STATE_NONE)
    if state == STATE_AWAITING_PDF_NAME:
        # Обрабатываем ввод имени PDF
        if not text:
            await update.message.reply_text(
                "Имя файла не может быть пустым. Попробуйте снова:",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Отмена", callback_data="cancel")
                ]])
            )
            return
        filename = text.replace("/", "").replace("\\", "").strip()
        if not filename:
            await update.message.reply_text(
                "Имя файла содержит только недопустимые символы. Попробуйте снова:",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Отмена", callback_data="cancel")
                ]])
            )
            return
        context.user_data['pdf_filename'] = filename
        context.user_data['state'] = STATE_NONE
        await update.message.reply_text(
            f"Имя файла установлено: {filename}.pdf",
            reply_markup=get_main_menu()
        )
    elif state == STATE_AWAITING_REORDER:
        image_files = context.user_data.get('image_files', [])
        if not image_files:
            context.user_data['state'] = STATE_NONE
            await update.message.reply_text(
                "Нет изображений для изменения порядка.",
                reply_markup=get_main_menu()
            )
            return
        try:
            new_order = [int(i) - 1 for i in text.split()]
            num_images = len(image_files)
            if len(new_order) != num_images:
                raise ValueError(f"Укажите ровно {num_images} индексов.")
            if any(i < 0 or i >= num_images for i in new_order):
                raise ValueError(f"Индексы должны быть числами от 1 до {num_images}.")
            if len(set(new_order)) != num_images:
                raise ValueError(f"Индексы должны быть уникальными и охватывать все изображения.")
            new_image_files = [image_files[i] for i in new_order]
            context.user_data['image_files'] = new_image_files
            message = "Новый порядок изображений:\n" + "\n".join(
                f"{i + 1}. {os.path.basename(f)}" for i, f in enumerate(new_image_files)
            )
            context.user_data['state'] = STATE_NONE
            await update.message.reply_text(
                message + "\nГотово! Используйте меню для дальнейших действий.",
                reply_markup=get_main_menu()
            )
        except Exception as e:
            await update.message.reply_text(
                f"Ошибка: {str(e)}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Отмена", callback_data="cancel")
                ]])
            )

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику по пользователям."""
    users = load_users()
    total_users = len(users)
    await update.callback_query.message.reply_text(
        f"📊 Всего пользователей: {total_users}",
        reply_markup=get_main_menu()
    )

async def convert_to_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Конвертирует изображения в PDF."""
    query = update.callback_query
    user_id = query.from_user.id
    user_dir = os.path.join(TEMP_DIR, str(user_id))
    if 'image_files' not in context.user_data or not context.user_data['image_files']:
        await query.message.reply_text(
            "Вы не отправили ни одного изображения!",
            reply_markup=get_main_menu()
        )
        return
    image_files = context.user_data['image_files']
    valid_image_files = [
        f for f in image_files if os.path.exists(f) and f.lower().endswith(('jpg', 'jpeg', 'png'))
    ]
    if not valid_image_files:
        await query.message.reply_text(
            "Нет поддерживаемых изображений для конвертации!",
            reply_markup=get_main_menu()
        )
        return
    debug_message = "Порядок изображений для PDF:\n" + "\n".join(
        f"{i + 1}. {os.path.basename(f)}" for i, f in enumerate(valid_image_files)
    )
    await query.message.reply_text(debug_message)
    custom_filename = context.user_data.get('pdf_filename', f"output_{user_id}")
    pdf_filename = f"{custom_filename}.pdf"
    pdf_path = os.path.join(user_dir, pdf_filename)
    try:
        images = [Image.open(f).convert('RGB') for f in valid_image_files]
        images[0].save(pdf_path, "PDF", resolution=100.0, save_all=True, append_images=images[1:])
    except Exception as e:
        await query.message.reply_text(
            f"Ошибка при создании PDF: {str(e)}",
            reply_markup=get_main_menu()
        )
        return
    with open(pdf_path, 'rb') as pdf_file:
        await query.message.reply_document(
            document=pdf_file,
            filename=pdf_filename,
            reply_markup=get_main_menu()
        )
    shutil.rmtree(user_dir)
    context.user_data.pop('pdf_filename', None)
    context.user_data.pop('image_files', None)
    context.user_data['state'] = STATE_NONE
    await query.message.reply_text(
        "PDF отправлен! Можете отправлять новые изображения.",
        reply_markup=get_main_menu()
    )

def main():
    # Создаём временную папку, если её нет
    if not os.path.exists(TEMP_DIR):
        os.makedirs(TEMP_DIR)
    # Инициализируем приложение
    application = Application.builder().token(TOKEN).build()
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(CallbackQueryHandler(handle_button))
    application.add_handler(CallbackQueryHandler(cancel, pattern="cancel"))
    application.add_handler(CommandHandler("stats", show_stats))
    # Запускаем бота
    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()