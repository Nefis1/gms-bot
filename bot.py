import logging
import io
import pandas as pd
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, MenuButtonCommands, BotCommand, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters
)
from telegram.constants import ParseMode
from datetime import datetime, timedelta

from config import BOT_TOKEN, GROUP_ID, MSK_TIMEZONE_OFFSET
from database import Database
from utils import format_ticket_message, get_current_shift, get_msk_time, format_msk_time, get_available_mixers, format_status_ru, format_step_ru, format_time_elapsed

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния разговора
(
    MAIN_MENU,
    PRODUCTION_MENU,
    LAB_MENU,
    NEW_BATCH_PRODUCT,
    NEW_BATCH_BRAND,
    NEW_BATCH_TECHNOLOGY,
    NEW_BATCH_MIXER,
    CONFIRM_START,
    ACTION_MENU,
    SAMPLE_SENT,
    SAMPLE_RECEIVED,
    ANALYSIS_RESULT,
    CORRECTION_NOTE,
    CONFIRM_DISCHARGE,
    FINAL_APPROVAL
) = range(15)

db = Database()

async def post_init(application: Application) -> None:
    """Установка меню бота после инициализации"""
    commands = [
        BotCommand("start", "Запустить систему"),
        BotCommand("status", "Статус миксеров"),
        BotCommand("active", "Активные тикеты"),
        BotCommand("lab", "Тикеты в лаборатории"),
        BotCommand("shift", "Статистика смены"),
        BotCommand("export", "Выгрузить Excel"),
        BotCommand("help", "Помощь")
    ]
    await application.bot.set_my_commands(commands)
    menu_button = MenuButtonCommands()
    await application.bot.set_chat_menu_button(menu_button=menu_button)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало работы с системой"""
    user = update.message.from_user
    context.user_data['username'] = user.username or user.first_name

    keyboard = [["🏭 Производство", "🔬 Лаборатория"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "🏭 Система сопровождения производственного процесса\n\n"
        "Выберите раздел:",
        reply_markup=reply_markup
    )

    return MAIN_MENU

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка главного меню"""
    text = update.message.text

    if "🏭 Производство" in text:
        keyboard = [["🆕 Новый замес", "🔧 Выполнить действия", "📊 Текущий статус"], ["🔙 Назад"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("🏭 Раздел Производства:", reply_markup=reply_markup)
        return PRODUCTION_MENU

    elif "🔬 Лаборатория" in text:
        keyboard = [["🔧 Выполнить действия", "📈 Текущие анализы"], ["🔙 Назад"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("🔬 Раздел Лаборатории:", reply_markup=reply_markup)
        return LAB_MENU

    elif "🔙 Назад" in text:
        return await start(update, context)

    return MAIN_MENU

# ПРОИЗВОДСТВО: Новый замес
async def production_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Меню производства"""
    text = update.message.text

    if "🔙 Назад" in text:
        return await start(update, context)

    elif "🆕 Новый замес" in text:
        # Очищаем данные о предыдущем создании тикета
        if 'ticket_created' in context.user_data:
            del context.user_data['ticket_created']
        
        keyboard = [["Гель", "Посуда", "АШ", "Кондиционер"], ["🔙 Назад"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Выберите продукт:", reply_markup=reply_markup)
        return NEW_BATCH_PRODUCT

    elif "🔧 Выполнить действия" in text:
        tickets = db.get_production_tickets()
        if not tickets:
            await update.message.reply_text("✅ Нет активных заданий для производства.")
            return PRODUCTION_MENU
        
        # Показываем список тикетов для действий с русскими статусами
        keyboard = []
        step_map = {
            'awaiting_sample': 'Ожид. пробу',
            'awaiting_lab_reception': 'Ожид. лаб', 
            'analysis_in_progress': 'Анализ',
            'awaiting_discharge': 'Ожид. откачки',
            'awaiting_correction': 'Ожид. исправления'
        }
        
        for ticket in tickets:
            step_text = step_map.get(ticket.get('current_step', ''), ticket.get('current_step', 'Новый'))
            btn_text = f"🎫 {ticket['ticket_id']} - {ticket['mixer']} - {step_text}"
            keyboard.append([btn_text])
        keyboard.append(["🔙 Назад"])
        
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Выберите тикет для действия:", reply_markup=reply_markup)
        context.user_data['action_tickets'] = {t['ticket_id']: t for t in tickets}
        return ACTION_MENU

    elif "📊 Текущий статус" in text:
        return await show_mixer_status(update, context)

    return PRODUCTION_MENU

# Процесс создания нового тикета
async def new_batch_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор продукта"""
    text = update.message.text

    if "🔙 Назад" in text:
        return await production_menu(update, context)

    context.user_data['product'] = text

    from config import BRANDS
    keyboard = [[brand] for brand in BRANDS]
    keyboard.append(["🔙 Назад"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Выберите бренд:", reply_markup=reply_markup)

    return NEW_BATCH_BRAND

async def new_batch_brand(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор бренда"""
    text = update.message.text

    if "🔙 Назад" in text:
        return await new_batch_product(update, context)

    context.user_data['brand'] = text

    keyboard = [["Старая технология", "Новая технология"], ["🔙 Назад"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Выберите технологию:", reply_markup=reply_markup)

    return NEW_BATCH_TECHNOLOGY

async def new_batch_technology(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор технологии"""
    text = update.message.text

    if "🔙 Назад" in text:
        return await new_batch_brand(update, context)

    context.user_data['technology'] = text

    # Получаем доступные миксеры
    product = context.user_data['product']
    technology = context.user_data['technology']
    available_mixers = get_available_mixers(product, technology)

    if not available_mixers:
        # Показываем сообщение и возвращаем к выбору технологии
        await update.message.reply_text("❌ Для выбранного продукта и технологии нет доступных миксеров. Выберите другую технологию:")
        return NEW_BATCH_TECHNOLOGY

    # Создаем клавиатуру с миксерами
    keyboard = []
    row = []
    for i, mixer in enumerate(available_mixers):
        row.append(mixer)
        if (i + 1) % 3 == 0:  # 3 кнопки в строке
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append(["🔙 Назад"])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Выберите миксер:", reply_markup=reply_markup)

    return NEW_BATCH_MIXER

async def new_batch_mixer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор миксера"""
    text = update.message.text

    if "🔙 Назад" in text:
        return await new_batch_technology(update, context)

    context.user_data['mixer'] = text

    # Подтверждение создания тикета
    product = context.user_data['product']
    brand = context.user_data['brand']
    technology = context.user_data['technology']
    mixer = context.user_data['mixer']

    keyboard = [["✅ Старт"], ["🔙 Назад"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        f"🎫 Создание нового тикета:\n\n"
        f"🏷️ Продукт: {product}\n"
        f"🏷️ Бренд: {brand}\n"
        f"🔧 Технология: {technology}\n"
        f"⚗️ Миксер: {mixer}\n\n"
        f"Подтвердите создание тикета:",
        reply_markup=reply_markup
    )

    return CONFIRM_START

async def confirm_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение старта тикета"""
    text = update.message.text

    if "🔙 Назад" in text:
        return await new_batch_mixer(update, context)

    if "✅ Старт" in text:
        try:
            print(f"DEBUG: Создание тикета с данными: {context.user_data}")

            # Проверяем занятость миксера
            mixer = context.user_data['mixer']
            if db.is_mixer_busy(mixer):
                await update.message.reply_text(f"❌ Миксер {mixer} сейчас занят! Выберите другой миксер.")
                return await new_batch_mixer(update, context)

            # Создаем тикет
            ticket_data = {
                'username': context.user_data['username'],
                'product': context.user_data['product'],
                'brand': context.user_data['brand'],
                'technology': context.user_data['technology'],
                'mixer': context.user_data['mixer']
            }

            ticket_id = db.create_ticket(ticket_data)
            print(f"DEBUG: Тикет создан: {ticket_id}")

            # Отправляем уведомление в группу
            ticket = db.get_ticket(ticket_id)
            message = format_ticket_message(ticket)

            await context.bot.send_message(
                chat_id=GROUP_ID,
                text=message
            )

            await update.message.reply_text(
                f"✅ Тикет {ticket_id} создан!\n\n"
                f"Следующий шаг: отобрать пробу и передать в лабораторию в течение 70 минут."
            )

            # Очищаем данные о создании тикета
            keys_to_clear = ['product', 'brand', 'technology', 'mixer']
            for key in keys_to_clear:
                if key in context.user_data:
                    del context.user_data[key]

        except ValueError as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
            return await new_batch_mixer(update, context)

        return await production_menu(update, context)

    return CONFIRM_START

# Действия с тикетами
async def action_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Меню действий с тикетом"""
    text = update.message.text

    if "🔙 Назад" in text:
        return await production_menu(update, context)

    # Определяем выбранный тикет
    if 'action_tickets' in context.user_data:
        for ticket_id, ticket in context.user_data['action_tickets'].items():
            if ticket_id in text:
                context.user_data['current_ticket'] = ticket
                break

        ticket = context.user_data.get('current_ticket')
        if ticket:
            # Показываем доступные действия для тикета
            status = ticket['status']
            keyboard = []

            if status in ['production_started', 'awaiting_sample', 'correction_required']:
                keyboard.append(["📤 Проба передана в лабораторию"])

            if status == 'awaiting_discharge':
                keyboard.append(["✅ Миксер откачан"])

            keyboard.append(["🔙 Назад"])

            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

            status_text = {
                'production_started': 'Ожидание отбора пробы',
                'awaiting_sample': 'Ожидание передачи пробы в лабораторию',
                'correction_required': 'Требуется корректировка',
                'awaiting_discharge': 'Ожидание откачки миксера'
            }

            await update.message.reply_text(
                f"🎫 Тикет {ticket['ticket_id']}\n"
                f"⚗️ {ticket['mixer']} | {ticket['product']}\n"
                f"📊 {status_text.get(status, status)}\n\n"
                f"Выберите действие:",
                reply_markup=reply_markup
            )

            return SAMPLE_SENT

    return ACTION_MENU

async def sample_sent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение передачи пробы"""
    text = update.message.text
    ticket = context.user_data.get('current_ticket')

    if "🔙 Назад" in text:
        return await action_menu(update, context)

    if "📤 Проба передана в лабораторию" in text and ticket:
        # Обновляем статус тикета - теперь он переходит в лабораторию
        db.update_ticket(ticket['ticket_id'], {
            'status': 'sample_sent',
            'current_step': 'awaiting_lab_reception',
            'action': 'sample_sent_to_lab',
            'username': context.user_data['username']
        })

        # Уведомление в группу
        updated_ticket = db.get_ticket(ticket['ticket_id'])
        message = format_ticket_message(updated_ticket)
        await context.bot.send_message(GROUP_ID, text=message)

        await update.message.reply_text("✅ Проба передана в лабораторию! Ожидайте результатов анализа.")

    elif "✅ Миксер откачан" in text and ticket:
        # Завершаем тикет - миксер освобождается
        db.update_ticket(ticket['ticket_id'], {
            'status': 'completed',
            'current_step': 'completed',
            'action': 'mixer_discharged',
            'username': context.user_data['username']
        })

        updated_ticket = db.get_ticket(ticket['ticket_id'])
        message = format_ticket_message(updated_ticket)
        await context.bot.send_message(GROUP_ID, text=message)

        await update.message.reply_text("✅ Тикет завершен! Миксер свободен для новых заданий.")

    # Очищаем текущий тикет
    if 'current_ticket' in context.user_data:
        del context.user_data['current_ticket']
    if 'action_tickets' in context.user_data:
        del context.user_data['action_tickets']

    return await start(update, context)

# ЛАБОРАТОРИЯ
async def lab_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Меню лаборатории"""
    text = update.message.text

    if "🔙 Назад" in text:
        return await start(update, context)

    elif "🔧 Выполнить действия" in text:
        tickets = db.get_lab_tickets()
        if not tickets:
            await update.message.reply_text("✅ Нет активных анализов для выполнения.")
            return LAB_MENU

        # Показываем список тикетов для лаборатории с русскими статусами
        keyboard = []
        step_map = {
            'awaiting_lab_reception': 'Ожид. приема',
            'analysis_in_progress': 'Анализ'
        }
        
        for ticket in tickets:
            step_text = step_map.get(ticket.get('current_step', ''), ticket.get('current_step', 'В работе'))
            btn_text = f"🎫 {ticket['ticket_id']} - {ticket['mixer']} - {step_text}"
            keyboard.append([btn_text])
        keyboard.append(["🔙 Назад"])

        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Выберите тикет для действия:", reply_markup=reply_markup)
        context.user_data['lab_tickets'] = {t['ticket_id']: t for t in tickets}
        return SAMPLE_RECEIVED

    elif "📈 Текущие анализы" in text:
        tickets = db.get_lab_tickets()
        if not tickets:
            await update.message.reply_text("📭 Нет активных анализов.")
            return LAB_MENU

        message = "🔬 Текущие анализы:\n\n"
        for ticket in tickets:
            step_map = {
                'awaiting_lab_reception': 'Ожидание приема',
                'analysis_in_progress': 'Анализ в процессе'
            }
            step_text = step_map.get(ticket.get('current_step', ''), ticket.get('current_step', 'В процессе'))
            message += f"🎫 {ticket['ticket_id']} - {ticket['mixer']}\n"
            message += f"   🏷️ {ticket['product']} | {ticket['brand']}\n"
            message += f"   ⏱️ Статус: {step_text}\n\n"

        await update.message.reply_text(message)
        return LAB_MENU

    return LAB_MENU

async def sample_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Действия лаборатории"""
    text = update.message.text
    ticket = None

    if "🔙 Назад" in text:
        return await lab_menu(update, context)

    # Находим тикет
    if 'lab_tickets' in context.user_data:
        for ticket_id, t in context.user_data['lab_tickets'].items():
            if ticket_id in text:
                ticket = t
                context.user_data['current_ticket'] = ticket
                break

    if ticket:
        # Показываем действия для лаборатории
        if ticket.get('status') == 'sample_sent':
            keyboard = [["✅ Принято в анализ"], ["🔙 Назад"]]
            action_text = "Подтвердите прием пробы в анализ:"
        else:
            keyboard = [["✅ Допущен", "⚠️ Корректировка"], ["🔙 Назад"]]
            action_text = "Выберите результат анализа:"
            
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

        await update.message.reply_text(
            f"🔬 Тикет {ticket['ticket_id']}\n"
            f"⚗️ {ticket['mixer']} | {ticket['product']}\n\n"
            f"{action_text}",
            reply_markup=reply_markup
        )

        return ANALYSIS_RESULT

    return SAMPLE_RECEIVED

async def analysis_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Результат анализа"""
    text = update.message.text
    ticket = context.user_data.get('current_ticket')

    if "🔙 Назад" in text:
        return await sample_received(update, context)

    if "✅ Принято в анализ" in text and ticket:
        # Обновляем статус - проба принята в лаборатории
        db.update_ticket(ticket['ticket_id'], {
            'status': 'sample_received',
            'current_step': 'analysis_in_progress',
            'action': 'sample_received_by_lab',
            'username': context.user_data['username']
        })

        # Отправляем сообщение в группу
        message = f"🎫 Тикет {ticket['ticket_id']}\n"
        message += f"🏷️ Продукт: {ticket['product']}\n"
        message += f"⚗️ Миксер: {ticket['mixer']}\n"
        message += f"📊 Статус: проба в лабе\n"
        message += f"👤 Ответственный: {context.user_data['username']}\n"
        message += f"🔰 Шаг: Анализ"

        await context.bot.send_message(GROUP_ID, text=message)
        
        # НЕ запрашиваем результат анализа сразу
        await update.message.reply_text(
            "✅ Проба принята в анализ! Продолжайте работу.\n\n"
            "Когда анализ будет готов, вернитесь в раздел Лаборатория → "
            "Выполнить действия для ввода результатов."
        )
        
        # Очищаем данные и возвращаем в главное меню
        if 'current_ticket' in context.user_data:
            del context.user_data['current_ticket']
        if 'lab_tickets' in context.user_data:
            del context.user_data['lab_tickets']
            
        return await start(update, context)

    elif "✅ Допущен" in text and ticket:
        # Запрашиваем финальное подтверждение с показателями
        keyboard = [["🔙 Назад"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "Внимание! Это финальное заключение по данному замесу, если замес еще требует корректировки нажмите Назад, если замес допускается, то введите показатели текстом",
            reply_markup=reply_markup
        )
        
        context.user_data['awaiting_final_approval'] = True
        return FINAL_APPROVAL

    elif "⚠️ Корректировка" in text and ticket:
        await update.message.reply_text(
            "Укажите необходимую корректировку:",
            reply_markup=ReplyKeyboardRemove()
        )
        return CORRECTION_NOTE

    return ANALYSIS_RESULT

async def correction_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ввод корректировки"""
    text = update.message.text
    ticket = context.user_data.get('current_ticket')

    if text == "🔙 Назад":
        return await analysis_result(update, context)

    if ticket and text:
        # Возвращаем тикет в производство для корректировки
        db.update_ticket(ticket['ticket_id'], {
            'status': 'correction_required',
            'current_step': 'awaiting_correction',
            'action': 'correction_required',
            'username': context.user_data['username'],
            'correction_note': text
        })

        updated_ticket = db.get_ticket(ticket['ticket_id'])
        message = format_ticket_message(updated_ticket)
        message += f"\n📝 Корректировка: {text}"

        await context.bot.send_message(GROUP_ID, text=message)
        await update.message.reply_text("✅ Корректировка отправлена в производство!")
        
        # Очищаем данные
        if 'current_ticket' in context.user_data:
            del context.user_data['current_ticket']
        if 'lab_tickets' in context.user_data:
            del context.user_data['lab_tickets']
            
        return await start(update, context)

    return CORRECTION_NOTE

async def final_approval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Финальное подтверждение допуска с показателями"""
    text = update.message.text
    ticket = context.user_data.get('current_ticket')

    if "🔙 Назад" in text:
        # Возвращаем к выбору действия
        keyboard = [["✅ Допущен", "⚠️ Корректировка"], ["🔙 Назад"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)
        return ANALYSIS_RESULT

    if ticket and text and context.user_data.get('awaiting_final_approval'):
        # Сохраняем показатели в историю анализов
        analysis_details = f"Показатели: {text}"
        
        # Обновляем тикет - продукт допущен
        db.update_ticket(ticket['ticket_id'], {
            'status': 'awaiting_discharge',
            'current_step': 'awaiting_discharge', 
            'action': 'analysis_approved',
            'username': context.user_data['username']
        })

        # Добавляем показатели в историю анализов
        updated_ticket = db.get_ticket(ticket['ticket_id'])
        if 'analyses_history' not in updated_ticket:
            updated_ticket['analyses_history'] = []
            
        updated_ticket['analyses_history'].append({
            'timestamp': format_msk_time(get_msk_time()),
            'user': context.user_data['username'],
            'result': 'approved',
            'details': analysis_details,
            'analysis_number': len(updated_ticket.get('analyses_history', [])) + 1
        })
        
        # Сохраняем обновленный тикет
        tickets = db._load_tickets()
        for i, t in enumerate(tickets):
            if t['ticket_id'] == ticket['ticket_id']:
                tickets[i] = updated_ticket
                break
        db._save_tickets(tickets)

        # Отправляем сообщение в группу
        message = f"🎫 Тикет {ticket['ticket_id']}\n"
        message += f"🏷️ Продукт: {ticket['product']}\n" 
        message += f"⚗️ Миксер: {ticket['mixer']}\n"
        message += f"📊 Статус: Допущен\n"
        message += f"👤 Ответственный: {context.user_data['username']}\n"
        message += f"🔰 Шаг: Ожидание откачки\n"
        message += f"📈 Показатели: {text}"

        await context.bot.send_message(GROUP_ID, text=message)

        await update.message.reply_text(
            f"✅ Продукт допущен в производство!\n"
            f"📊 Показатели: {text}\n\n"
            f"Ожидайте откачки миксера."
        )

        # Очищаем данные
        keys_to_clear = ['current_ticket', 'lab_tickets', 'awaiting_final_approval']
        for key in keys_to_clear:
            if key in context.user_data:
                del context.user_data[key]

        return await start(update, context)

    return FINAL_APPROVAL

# НОВЫЕ КОМАНДЫ МЕНЮ
async def show_mixer_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статус миксеров (для команды /status и кнопки)"""
    try:
        status = db.get_mixer_status()
        message = "📊 Статус миксеров:\n\n"

        for mixer, info in status.items():
            if info.get('status') == 'free':
                message += f"✅ {mixer}: Свободен\n"
            else:
                step_map = {
                    'awaiting_sample': 'Ожид. пробу',
                    'awaiting_lab_reception': 'Ожид. лаб',
                    'analysis_in_progress': 'Анализ',
                    'awaiting_discharge': 'Ожид. откачки',
                    'awaiting_correction': 'Ожид. исправления'
                }
                step_text = step_map.get(info.get('current_step', ''), info.get('current_step', 'В работе'))
                
                # Форматируем время
                total_minutes = info.get('total_time_minutes', 0)
                if total_minutes < 60:
                    time_text = f"{total_minutes} мин"
                else:
                    hours = total_minutes // 60
                    mins = total_minutes % 60
                    time_text = f"{hours}ч {mins}мин"
                
                message += f"🔄 {mixer}: {info.get('product', 'N/A')} ({info.get('ticket_id', 'N/A')})\n"
                message += f"   Шаг: {step_text}\n"
                message += f"   Время: {time_text}\n\n"

        await update.message.reply_text(message)
        
    except Exception as e:
        logger.error(f"Ошибка при показе статуса: {e}")
        await update.message.reply_text("❌ Ошибка при получении статуса миксеров")

async def show_active_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает активные тикеты"""
    try:
        active_tickets = db.get_active_tickets()
        
        if not active_tickets:
            await update.message.reply_text("✅ Нет активных тикетов")
            return
        
        message = "🎫 Активные тикеты:\n\n"
        for ticket in active_tickets:
            status_map = {
                'production_started': '🏭 Производство',
                'awaiting_sample': '⏳ Ожидание пробы',
                'sample_sent': '📤 Проба отправлена',
                'sample_received': '🔬 В лаборатории',
                'analysis_in_progress': '⚗️ Анализ',
                'correction_required': '⚠️ Корректировка',
                'awaiting_discharge': '🔄 Ожидание откачки'
            }
            
            status_text = status_map.get(ticket['status'], ticket['status'])
            message += f"• {ticket['ticket_id']} - {ticket['mixer']}\n"
            message += f"  {ticket['product']} | {ticket['brand']}\n"
            message += f"  {status_text}\n\n"
        
        await update.message.reply_text(message)
        
    except Exception as e:
        await update.message.reply_text("❌ Ошибка при получении тикетов")

async def show_lab_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает тикеты в лаборатории"""
    try:
        lab_tickets = db.get_lab_tickets()
        
        if not lab_tickets:
            await update.message.reply_text("🔬 Нет тикетов в лаборатории")
            return
        
        message = "🔬 Тикеты в лаборатории:\n\n"
        for ticket in lab_tickets:
            step_map = {
                'sample_sent': '📤 Ожидание приема',
                'sample_received': '🔬 Принята',
                'analysis_in_progress': '⚗️ Анализ'
            }
            
            step_text = step_map.get(ticket['status'], ticket['status'])
            message += f"• {ticket['ticket_id']} - {ticket['mixer']}\n"
            message += f"  {ticket['product']} | {step_text}\n"
            
            # Показываем время с создания
            created_at_str = ticket['created_at']
            if 'Z' in created_at_str:
                created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                created_at = created_at + timedelta(hours=MSK_TIMEZONE_OFFSET)
                created_at = created_at.replace(tzinfo=None)
            else:
                created_at_str = created_at_str.split('+')[0]
                created_at = datetime.fromisoformat(created_at_str)
            
            now = datetime.now()
            elapsed = now - created_at
            minutes = int(elapsed.total_seconds() / 60)
            
            if minutes < 60:
                message += f"  Время: {minutes} мин\n\n"
            else:
                hours = minutes // 60
                mins = minutes % 60
                message += f"  Время: {hours}ч {mins}мин\n\n"
        
        await update.message.reply_text(message)
        
    except Exception as e:
        await update.message.reply_text("❌ Ошибка при получении лабораторных тикетов")

async def show_shift_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику текущей смены"""
    try:
        current_shift = get_current_shift()
        
        # Получаем тикеты за текущую смену
        shift_start_hour = 7 if current_shift == "дневная" else 19
        now = get_msk_time().replace(tzinfo=None)
        shift_start = datetime(now.year, now.month, now.day, shift_start_hour, 0, 0)
        if now.hour < shift_start_hour:
            shift_start = shift_start - timedelta(days=1)

        all_tickets = db._load_tickets()
        archive_tickets = db._load_archive()
        all_tickets_combined = all_tickets + archive_tickets

        shift_tickets = []
        for ticket in all_tickets_combined:
            created_at_str = ticket['created_at']
            if 'Z' in created_at_str:
                created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                created_at = created_at.replace(tzinfo=None)
            else:
                created_at_str = created_at_str.split('+')[0]
                created_at = datetime.fromisoformat(created_at_str)
                
            if created_at >= shift_start:
                shift_tickets.append(ticket)
        
        stats = {
            'total': len(shift_tickets),
            'production': len([t for t in shift_tickets if t.get('status') in ['production_started', 'awaiting_sample', 'correction_required', 'awaiting_discharge']]),
            'lab': len([t for t in shift_tickets if t.get('status') in ['sample_sent', 'sample_received', 'analysis_in_progress']]),
            'completed': len([t for t in shift_tickets if t.get('status') == 'completed'])
        }
        
        message = f"📊 {current_shift.capitalize()} смена:\n\n"
        message += f"🎫 Всего тикетов: {stats['total']}\n"
        message += f"🏭 В производстве: {stats['production']}\n"
        message += f"🔬 В лаборатории: {stats['lab']}\n"
        message += f"✅ Завершено: {stats['completed']}\n\n"
        
        if stats['total'] > 0:
            completion_rate = (stats['completed'] / stats['total']) * 100
            message += f"📈 Эффективность: {completion_rate:.1f}%"
        
        await update.message.reply_text(message)
        
    except Exception as e:
        await update.message.reply_text("❌ Ошибка при получении статистики смены")

async def export_to_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выгружает данные в Excel файл с московским временем"""
    try:
        await update.message.reply_text("📊 Формирую Excel файл...")
        
        # Используем существующую логику из app.py
        tickets = db._load_tickets()
        archive = db._load_archive()
        all_tickets = tickets + archive

        if not all_tickets:
            await update.message.reply_text("❌ Нет данных для экспорта")
            return

        # Преобразуем данные для Excel
        data = []
        for ticket in all_tickets:
            corrections_count = len(ticket.get('corrections_history', []))
            analyses_count = len(ticket.get('analyses_history', []))

            # Форматируем историю корректировок с МСК временем
            corrections_text = ""
            if ticket.get('corrections_history'):
                for i, correction in enumerate(ticket['corrections_history'], 1):
                    timestamp_str = correction.get('timestamp', '')
                    # Конвертируем в МСК время
                    if 'T' in timestamp_str:
                        try:
                            # Обрабатываем время как мы делали в других функциях
                            if 'Z' in timestamp_str:
                                dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                                dt = dt + timedelta(hours=MSK_TIMEZONE_OFFSET)
                            else:
                                timestamp_str = timestamp_str.split('+')[0]
                                dt = datetime.fromisoformat(timestamp_str)
                            
                            # Форматируем в читаемый вид
                            msk_time = dt.strftime("%d.%m.%Y %H:%M:%S")
                            corrections_text += f"{i}. {msk_time} - {correction.get('user', '')}: {correction.get('note', '')}\n"
                        except:
                            corrections_text += f"{i}. {timestamp_str} - {correction.get('user', '')}: {correction.get('note', '')}\n"
                    else:
                        corrections_text += f"{i}. {timestamp_str} - {correction.get('user', '')}: {correction.get('note', '')}\n"

            # Форматируем историю анализов с МСК временем
            analyses_text = ""
            if ticket.get('analyses_history'):
                for i, analysis in enumerate(ticket['analyses_history'], 1):
                    result = "Допущен" if analysis.get('result') == 'approved' else "Отклонен"
                    timestamp_str = analysis.get('timestamp', '')
                    
                    # Конвертируем в МСК время
                    if 'T' in timestamp_str:
                        try:
                            if 'Z' in timestamp_str:
                                dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                                dt = dt + timedelta(hours=MSK_TIMEZONE_OFFSET)
                            else:
                                timestamp_str = timestamp_str.split('+')[0]
                                dt = datetime.fromisoformat(timestamp_str)
                            
                            msk_time = dt.strftime("%d.%m.%Y %H:%M:%S")
                            analyses_text += f"{i}. {msk_time} - {analysis.get('user', '')}: {result} - {analysis.get('details', '')}\n"
                        except:
                            analyses_text += f"{i}. {timestamp_str} - {analysis.get('user', '')}: {result} - {analysis.get('details', '')}\n"
                    else:
                        analyses_text += f"{i}. {timestamp_str} - {analysis.get('user', '')}: {result} - {analysis.get('details', '')}\n"

            # Форматируем время создания и завершения в МСК
            created_at_msk = ""
            if ticket.get('created_at'):
                created_str = ticket['created_at']
                try:
                    if 'Z' in created_str:
                        dt = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                        dt = dt + timedelta(hours=MSK_TIMEZONE_OFFSET)
                    else:
                        created_str = created_str.split('+')[0]
                        dt = datetime.fromisoformat(created_str)
                    created_at_msk = dt.strftime("%d.%m.%Y %H:%M:%S")
                except:
                    created_at_msk = created_str

            completed_at_msk = ""
            if ticket.get('completed_at'):
                completed_str = ticket['completed_at']
                try:
                    if 'Z' in completed_str:
                        dt = datetime.fromisoformat(completed_str.replace('Z', '+00:00'))
                        dt = dt + timedelta(hours=MSK_TIMEZONE_OFFSET)
                    else:
                        completed_str = completed_str.split('+')[0]
                        dt = datetime.fromisoformat(completed_str)
                    completed_at_msk = dt.strftime("%d.%m.%Y %H:%M:%S")
                except:
                    completed_at_msk = completed_str

            # Форматируем время производства в часах и минутах
            production_time_minutes = ticket.get('total_production_time_minutes', 0)
            if production_time_minutes:
                hours = production_time_minutes // 60
                minutes = production_time_minutes % 60
                if hours > 0:
                    production_time_formatted = f"{hours} часов {minutes} минут"
                else:
                    production_time_formatted = f"{minutes} минут"
            else:
                production_time_formatted = ""

            row = {
                'ID_тикета': ticket.get('ticket_id', ''),
                'Дата_создания_МСК': created_at_msk,
                'Дата_завершения_МСК': completed_at_msk,
                'Продукт': ticket.get('product', ''),
                'Бренд': ticket.get('brand', ''),
                'Технология': ticket.get('technology', ''),
                'Миксер': ticket.get('mixer', ''),
                'Статус': format_status_ru(ticket.get('status', '')),
                'Текущий_шаг': format_step_ru(ticket.get('current_step', '')),
                'Пользователь': ticket.get('username', ''),
                'Корректировки': corrections_count,
                'История_корректировок': corrections_text,
                'Анализы': analyses_count,
                'История_анализов': analyses_text,
                'Время_производства_мин': production_time_minutes,
                'Время_производства': production_time_formatted,  # НОВЫЙ СТОЛБЕЦ
            }
            data.append(row)

        # Создаем Excel файл в памяти
        df = pd.DataFrame(data)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Тикеты', index=False)
            
            # Настраиваем ширину колонок
            worksheet = writer.sheets['Тикеты']
            worksheet.column_dimensions['A'].width = 15
            worksheet.column_dimensions['B'].width = 20
            worksheet.column_dimensions['C'].width = 20
            worksheet.column_dimensions['D'].width = 15
            worksheet.column_dimensions['E'].width = 15
            worksheet.column_dimensions['F'].width = 20
            worksheet.column_dimensions['G'].width = 15
            worksheet.column_dimensions['H'].width = 20
            worksheet.column_dimensions['I'].width = 20
            worksheet.column_dimensions['J'].width = 15
            worksheet.column_dimensions['K'].width = 10
            worksheet.column_dimensions['L'].width = 50
            worksheet.column_dimensions['M'].width = 10
            worksheet.column_dimensions['N'].width = 50
            worksheet.column_dimensions['O'].width = 15
            worksheet.column_dimensions['P'].width = 20  # НОВАЯ КОЛОНКА

        output.seek(0)
        
        # Создаем имя файла с текущей МСК датой
        msk_now = get_msk_time()
        filename = f'production_tickets_{msk_now.strftime("%d-%m-%Y_%H-%M")}_MSK.xlsx'
        
        # Отправляем файл пользователю
        await update.message.reply_document(
            document=InputFile(output, filename=filename),
            caption=f"📊 Выгрузка данных на {msk_now.strftime('%d.%m.%Y %H:%M')} МСК\n"
                   f"Всего записей: {len(all_tickets)}"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при экспорте: {e}")
        await update.message.reply_text("❌ Ошибка при создании Excel файла")

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Расширенная помощь"""
    help_text = """
🤖 *Производственная система - Помощь*

*Основные команды:*
/start - Запустить систему
/status - Статус миксеров
/active - Активные тикеты
/lab - Тикеты в лаборатории  
/shift - Статистика смены
/export - Выгрузить Excel
/help - Эта справка

*Быстрые действия через меню:*
🏭 Производство - Создание тикетов и управление
🔬 Лаборатория - Работа с анализами

*Веб-интерфейс:*
Для детальной статистики и экспорта используйте веб-панель.

*Контакты:*
Для технических вопросов обращайтесь к разработчику.
"""
    await update.message.reply_text(help_text)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена операции"""
    context.user_data.clear()
    await update.message.reply_text(
        "🔄 Операция отменена.",
        reply_markup=ReplyKeyboardRemove()
    )
    return await start(update, context)

def main() -> None:
    """Запуск бота"""
    application = Application.builder().token(BOT_TOKEN).build()
    application.post_init = post_init

    # Обработчик разговора
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MAIN_MENU: [MessageHandler(filters.Regex(r"^(🏭 Производство|🔬 Лаборатория|🔙 Назад)$"), main_menu)],
            PRODUCTION_MENU: [MessageHandler(filters.Regex(r"^(🆕 Новый замес|🔧 Выполнить действия|📊 Текущий статус|🔙 Назад)$"), production_menu)],
            LAB_MENU: [MessageHandler(filters.Regex(r"^(🔧 Выполнить действия|📈 Текущие анализы|🔙 Назад)$"), lab_menu)],
            NEW_BATCH_PRODUCT: [MessageHandler(filters.Regex(r"^(Гель|Посуда|АШ|Кондиционер|🔙 Назад)$"), new_batch_product)],
            NEW_BATCH_BRAND: [MessageHandler(filters.Regex(r"^(AOS|Sorti|Биолан|Фритайм|Без названия|🔙 Назад)$"), new_batch_brand)],
            NEW_BATCH_TECHNOLOGY: [MessageHandler(filters.Regex(r"^(Старая технология|Новая технология|🔙 Назад)$"), new_batch_technology)],
            NEW_BATCH_MIXER: [MessageHandler(filters.Regex(r"^(Миксер_\d+|🔙 Назад)$"), new_batch_mixer)],
            CONFIRM_START: [MessageHandler(filters.Regex(r"^(✅ Старт|🔙 Назад)$"), confirm_start)],
            ACTION_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, action_menu)],
            SAMPLE_SENT: [MessageHandler(filters.Regex(r"^(📤 Проба передана в лабораторию|✅ Миксер откачан|🔙 Назад)$"), sample_sent)],
            SAMPLE_RECEIVED: [MessageHandler(filters.TEXT & ~filters.COMMAND, sample_received)],
            ANALYSIS_RESULT: [MessageHandler(filters.Regex(r"^(✅ Принято в анализ|✅ Допущен|⚠️ Корректировка|🔙 Назад)$"), analysis_result)],
            CORRECTION_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, correction_note)],
            FINAL_APPROVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, final_approval)],
        },
        fallbacks=[CommandHandler('cancel', cancel), CommandHandler('start', start)]
    )

    application.add_handler(conv_handler)
    
    # Регистрируем команды меню
    application.add_handler(CommandHandler('status', show_mixer_status))
    application.add_handler(CommandHandler('active', show_active_tickets))
    application.add_handler(CommandHandler('lab', show_lab_tickets))
    application.add_handler(CommandHandler('shift', show_shift_stats))
    application.add_handler(CommandHandler('export', export_to_excel))
    application.add_handler(CommandHandler('help', show_help))

    print("🏭 Производственная система запущена...")
    application.run_polling()

if __name__ == '__main__':
    main()