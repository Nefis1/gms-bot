import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, MenuButtonCommands, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters
)
from telegram.constants import ParseMode

from config import BOT_TOKEN, GROUP_ID
from database import Database
from utils import format_ticket_message, get_current_shift, get_msk_time, format_msk_time, get_available_mixers

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
    CONFIRM_DISCHARGE
) = range(14)

db = Database()

async def post_init(application: Application) -> None:
    """Установка меню бота после инициализации"""
    commands = [
        BotCommand("start", "Запустить систему"),
        BotCommand("status", "Текущий статус"),
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
                message += f"🔄 {mixer}: {info.get('product', 'N/A')} ({info.get('ticket_id', 'N/A')})\n"
                message += f"   Шаг: {step_text}\n"

        await update.message.reply_text(message)
        return PRODUCTION_MENU

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
                text=message,
                parse_mode=ParseMode.MARKDOWN
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
        await context.bot.send_message(GROUP_ID, text=message, parse_mode=ParseMode.MARKDOWN)

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
        await context.bot.send_message(GROUP_ID, text=message, parse_mode=ParseMode.MARKDOWN)

        await update.message.reply_text("✅ Тикет завершен! Миксер свободен для новых заданий.")

    # Очищаем текущий тикет
    if 'current_ticket' in context.user_data:
        del context.user_data['current_ticket']
    if 'action_tickets' in context.user_data:
        del context.user_data['action_tickets']

    return await production_menu(update, context)

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
            action_text = "Введите результат анализа:"
            
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

        # Запрашиваем результат анализа
        keyboard = [["✅ Допущен", "⚠️ Корректировка"], ["🔙 Назад"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

        await update.message.reply_text(
            "Введите результат анализа:",
            reply_markup=reply_markup
        )

        return ANALYSIS_RESULT

    elif "✅ Допущен" in text and ticket:
        # Продукт допущен - возвращаем в производство для откачки
        db.update_ticket(ticket['ticket_id'], {
            'status': 'awaiting_discharge',  # Теперь тикет возвращается в производство
            'current_step': 'awaiting_discharge',
            'action': 'analysis_approved',
            'username': context.user_data['username']
        })

        updated_ticket = db.get_ticket(ticket['ticket_id'])
        message = format_ticket_message(updated_ticket)
        await context.bot.send_message(GROUP_ID, text=message, parse_mode=ParseMode.MARKDOWN)

        await update.message.reply_text("✅ Продукт допущен в производство! Ожидайте откачки миксера.")
        
        # Очищаем данные
        if 'current_ticket' in context.user_data:
            del context.user_data['current_ticket']
        if 'lab_tickets' in context.user_data:
            del context.user_data['lab_tickets']
            
        return await lab_menu(update, context)

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
            
        return await lab_menu(update, context)

    return CORRECTION_NOTE

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
        },
        fallbacks=[CommandHandler('cancel', cancel), CommandHandler('start', start)]
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('status', production_menu))
    application.add_handler(CommandHandler('help', start))

    print("🏭 Производственная система запущена...")
    application.run_polling()

if __name__ == '__main__':
    main()