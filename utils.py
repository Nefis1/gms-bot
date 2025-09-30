from datetime import datetime, time, timedelta, timezone
from typing import Dict, Any, List
from config import DAY_SHIFT_START, NIGHT_SHIFT_START, MSK_TIMEZONE_OFFSET, PRODUCTION_TIMEOUT, LAB_TIMEOUT

def get_msk_time() -> datetime:
    """Возвращает текущее время по МСК"""
    utc_time = datetime.now(timezone.utc)
    msk_time = utc_time + timedelta(hours=MSK_TIMEZONE_OFFSET)
    return msk_time

def get_current_shift() -> str:
    """Возвращает текущую смену по МСК"""
    now = get_msk_time()
    current_hour = now.hour
    
    if DAY_SHIFT_START <= current_hour < NIGHT_SHIFT_START:
        return "дневная"
    else:
        return "ночная"

def format_msk_time(dt: datetime = None) -> str:
    """Форматирует время по МСК"""
    if dt is None:
        dt = get_msk_time()
    return dt.strftime("%d.%m.%Y %H:%M:%S")

def format_time_elapsed(time_input) -> str:
    """Форматирует время в минутах или timestamp в читаемый формат"""
    if isinstance(time_input, int):  # Если переданы минуты
        minutes = time_input
    else:  # Если передан timestamp
        if isinstance(time_input, str):
            # ИСПРАВЛЕНИЕ: корректная обработка времени с временными зонами
            time_str = time_input.split('+')[0]  # Убираем временную зону
            if 'Z' in time_str:
                past_time = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                past_time = past_time.replace(tzinfo=None)  # Делаем naive
            else:
                past_time = datetime.fromisoformat(time_str)
        else:
            # Если это datetime объект
            past_time = time_input.replace(tzinfo=None) if hasattr(time_input, 'tzinfo') and time_input.tzinfo else time_input
            
        now = datetime.now()
        elapsed = now - past_time
        minutes = int(elapsed.total_seconds() / 60)
    
    if minutes < 60:
        return f"{minutes} мин"
    else:
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}ч {mins}мин"

def format_ticket_message(ticket_data: Dict[str, Any]) -> str:
    """Форматирует сообщение о тикете для отправки в группу"""
    status_map = {
        'production_started': '🏭 Производство начато',
        'awaiting_sample': '⏳ Ожидание пробы',
        'sample_sent': '📤 Проба отправлена',
        'sample_received': '🔬 Проба принята',
        'analysis_in_progress': '⚗️ Анализ',
        'approved': '✅ Допущен',
        'correction_required': '⚠️ Корректировка',
        'awaiting_discharge': '🔄 Ожидание откачки',
        'completed': '🏁 Завершен'
    }
    
    # Сокращенные русские статусы для отображения
    current_step_map = {
        'awaiting_sample': 'Ожид. пробу',
        'awaiting_lab_reception': 'Ожид. лаб',
        'analysis_in_progress': 'Анализ',
        'awaiting_discharge': 'Ожид. откачки',
        'awaiting_correction': 'Ожид. исправления'
    }
    
    message = f"🎫  Тикет {ticket_data['ticket_id']}\n"
    message += f"🏷️ Продукт: {ticket_data['product']} | {ticket_data['brand']}\n"
    message += f"⚗️ Миксер: {ticket_data['mixer']}\n"
    message += f"📊 Статус: {status_map.get(ticket_data['status'], ticket_data['status'])}\n"
    message += f"👤 Ответственный: {ticket_data.get('username', 'N/A')}\n"
    
    if ticket_data.get('current_step'):
        step_text = current_step_map.get(ticket_data['current_step'], ticket_data['current_step'])
        message += f"🔰 Шаг: {step_text}\n"
    
    # Показываем количество корректировок если есть
    corrections_count = len(ticket_data.get('corrections_history', []))
    if corrections_count > 0:
        message += f"🔄 Корректировок: {corrections_count}\n"
    
    return message

def format_status_ru(status: str) -> str:
    """Форматирует статус на русский для веб-интерфейса"""
    status_map = {
        'free': 'Свободен',
        'production_started': 'Производство начато',
        'awaiting_sample': 'Ожидание пробы',
        'sample_sent': 'Проба отправлена',
        'sample_received': 'Проба принята',
        'analysis_in_progress': 'Анализ в процессе',
        'approved': 'Допущен',
        'correction_required': 'Требуется корректировка',
        'awaiting_discharge': 'Ожидание откачки',
        'completed': 'Завершен'
    }
    return status_map.get(status, status)

def format_step_ru(step: str) -> str:
    """Форматирует шаг на русский для веб-интерфейса"""
    step_map = {
        'awaiting_sample': 'Ожид. пробу',
        'awaiting_lab_reception': 'Ожид. лаб',
        'analysis_in_progress': 'Анализ',
        'awaiting_discharge': 'Ожид. откачки',
        'awaiting_correction': 'Ожид. исправления',
        'manually_closed': 'Закрыт вручную'
    }
    return step_map.get(step, step)

def check_timeout(ticket_data: Dict[str, Any]) -> Dict[str, Any]:
    """Проверяет таймауты для тикета"""
    now = datetime.now()  # naive datetime
    
    # Находим время последнего действия
    if ticket_data.get('history'):
        last_action = max(ticket_data['history'], key=lambda x: x['timestamp'])
        last_time_str = last_action['timestamp']
        
        # Конвертируем в naive datetime
        last_time_str = last_time_str.split('+')[0]  # Убираем временную зону
        if 'Z' in last_time_str:
            last_time = datetime.fromisoformat(last_time_str.replace('Z', '+00:00'))
            last_time = last_time.replace(tzinfo=None)
        else:
            last_time = datetime.fromisoformat(last_time_str)
        
        elapsed_minutes = (now - last_time).total_seconds() / 60
        
        # Проверяем таймауты в зависимости от статуса
        if ticket_data['status'] in ['awaiting_sample', 'correction_required']:
            if elapsed_minutes > PRODUCTION_TIMEOUT:
                return {'timed_out': True, 'message': '⚠️ ПРОСРОЧКА! Производство не отправило пробу вовремя'}
        
        elif ticket_data['status'] in ['sample_received', 'analysis_in_progress']:
            if elapsed_minutes > LAB_TIMEOUT:
                return {'timed_out': True, 'message': '⚠️ ПРОСРОЧКА! Лаборатория не провела анализ вовремя'}
    
    return {'timed_out': False}

def is_valid_number(input_str: str, value_type: str = "float") -> bool:
    """Проверяет, является ли ввод валидным числом"""
    try:
        if value_type == "float":
            value = float(input_str)
            return value >= 0
        elif value_type == "int":
            value = int(input_str)
            return value >= 0
        return False
    except ValueError:
        return False

def get_available_mixers(product: str, technology: str) -> List[str]:
    """Возвращает доступные миксеры для продукта и технологии"""
    from config import PRODUCT_MIXERS
    
    available = PRODUCT_MIXERS.get(product, [])
    
    # Фильтруем по технологии с учетом ограничений продукта
    if product == "Посуда" and technology == "Новая технология":
        # Для посуды новая технология не доступна
        available = []
    elif product == "АШ" and technology == "Старая технология":
        # Для АШ старая технология не доступна  
        available = []
    elif technology == "Старая технология":
        available = [m for m in available if m <= 8]
    elif technology == "Новая технология":
        available = [m for m in available if m >= 9]
    
    return [f"Миксер_{m}" for m in sorted(available)]