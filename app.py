from flask import Flask, render_template, jsonify, Response, request
import json
import os
from datetime import datetime, timedelta
import pandas as pd
import io
from database import Database
from utils import format_status_ru, format_step_ru, format_time_elapsed, get_current_shift, get_msk_time, format_msk_time

app = Flask(__name__)

# Инициализация базы данных
db = Database()

def get_tickets_for_current_shift():
    """Возвращает статистику тикетов за текущую смену"""
    current_shift = get_current_shift()
    shift_start_hour = 7 if current_shift == "дневная" else 19

    now = get_msk_time()
    shift_start = datetime(now.year, now.month, now.day, shift_start_hour, 0, 0)
    if now.hour < shift_start_hour:
        shift_start = shift_start - timedelta(days=1)

    all_tickets = db._load_tickets()
    archive_tickets = db._load_archive()
    all_tickets_combined = all_tickets + archive_tickets

    shift_tickets = []
    for ticket in all_tickets_combined:
        created_at = datetime.fromisoformat(ticket['created_at'])
        if created_at >= shift_start:
            shift_tickets.append(ticket)

    return shift_tickets

@app.route('/')
def index():
    """Главная страница с панелью управления"""
    try:
        # Получаем данные из базы
        all_tickets = db._load_tickets()
        active_tickets = db.get_active_tickets()
        mixer_status = db.get_mixer_status()

        # Статистика за текущую смену
        shift_tickets = get_tickets_for_current_shift()
        shift_stats = {
            'total': len([t for t in shift_tickets]),
            'production': len([t for t in shift_tickets if t.get('status') in ['production_started', 'awaiting_sample', 'correction_required', 'awaiting_discharge']]),
            'lab': len([t for t in shift_tickets if t.get('status') in ['sample_sent', 'sample_received', 'analysis_in_progress']]),
            'completed': len([t for t in shift_tickets if t.get('status') == 'completed'])
        }

        # Форматируем время для активных тикетов
        for ticket in active_tickets:
            if ticket.get('history'):
                last_action = max(ticket['history'], key=lambda x: x['timestamp'])
                ticket['last_update'] = format_time_elapsed(last_action['timestamp'])
            else:
                ticket['last_update'] = "N/A"

            # Добавляем русские статусы
            ticket['status_ru'] = format_status_ru(ticket.get('status', ''))
            ticket['step_ru'] = format_step_ru(ticket.get('current_step', ''))

        # Форматируем статус миксеров с русскими названиями
        for mixer, info in mixer_status.items():
            info['status_ru'] = format_status_ru(info.get('status', 'free'))
            info['step_ru'] = format_step_ru(info.get('current_step', ''))

            if info.get('status') != 'free' and info.get('ticket_id'):
                ticket = db.get_ticket(info['ticket_id'])
                if ticket and ticket.get('history'):
                    last_action = max(ticket['history'], key=lambda x: x['timestamp'])
                    info['time_elapsed'] = format_time_elapsed(last_action['timestamp'])

                    # Общее время производства
                    if info.get('total_time_minutes'):
                        info['total_time'] = format_time_elapsed(info['total_time_minutes'])
                    else:
                        info['total_time'] = "N/A"
                else:
                    info['time_elapsed'] = "N/A"
                    info['total_time'] = "N/A"

        stats = {
            'total_tickets': len(all_tickets),
            'production_tickets': len(db.get_production_tickets()),
            'lab_tickets': len(db.get_lab_tickets()),
            'completed_tickets': len([t for t in all_tickets if t.get('status') == 'completed']),
            'active_tickets_count': len(active_tickets),
            'shift_stats': shift_stats,
            'current_shift': get_current_shift()
        }

        return render_template('index.html',
                             stats=stats,
                             mixer_status=mixer_status,
                             active_tickets=active_tickets)

    except Exception as e:
        print(f"Ошибка в index: {e}")
        return f"Ошибка: {str(e)}", 500

@app.route('/stats')
def stats():
    """Страница со статистикой"""
    try:
        all_tickets = db._load_tickets()
        archive_tickets = db._load_archive()

        # Собираем статистику
        stats_data = {
            'total': len(all_tickets) + len(archive_tickets),
            'active': len(db.get_active_tickets()),
            'completed': len(archive_tickets),
            'correction_required': len([t for t in all_tickets if t.get('status') == 'correction_required']),
            'products': {},
            'technologies': {},
            'brands': {},
            'mixers': {},
            'avg_production_time': 0
        }

        # Статистика по всем тикетам (активные + архив)
        all_tickets_combined = all_tickets + archive_tickets

        # Статистика по продуктам, технологиям, брендам и миксерам
        for ticket in all_tickets_combined:
            # Продукты
            product = ticket.get('product', 'Не указан')
            stats_data['products'][product] = stats_data['products'].get(product, 0) + 1

            # Технологии
            technology = ticket.get('technology', 'Не указана')
            stats_data['technologies'][technology] = stats_data['technologies'].get(technology, 0) + 1

            # Бренды
            brand = ticket.get('brand', 'Не указан')
            stats_data['brands'][brand] = stats_data['brands'].get(brand, 0) + 1

            # Миксеры
            mixer = ticket.get('mixer', 'Не указан')
            stats_data['mixers'][mixer] = stats_data['mixers'].get(mixer, 0) + 1

        # Среднее время производства для завершенных тикетов
        completed_times = [t.get('total_production_time_minutes', 0) for t in archive_tickets if t.get('total_production_time_minutes')]
        if completed_times:
            stats_data['avg_production_time'] = format_time_elapsed(int(sum(completed_times) / len(completed_times)))

        return render_template('stats.html', stats=stats_data)

    except Exception as e:
        print(f"Ошибка в stats: {e}")
        return f"Ошибка: {str(e)}", 500

@app.route('/admin')
def admin_panel():
    """Панель администратора"""
    try:
        all_tickets = db._load_tickets()
        archive_tickets = db._load_archive()
        active_tickets = db.get_active_tickets()

        return render_template('admin.html',
                             total_tickets=len(all_tickets) + len(archive_tickets),
                             active_tickets=active_tickets,
                             archive_count=len(archive_tickets))

    except Exception as e:
        print(f"Ошибка в admin_panel: {e}")
        return f"Ошибка: {str(e)}", 500

@app.route('/export/excel')
def export_excel():
    """Экспорт данных в Excel с историей корректировок и временем МСК"""
    try:
        tickets = db._load_tickets()
        archive = db._load_archive()
        all_tickets = tickets + archive

        if not all_tickets:
            return "Нет данных для экспорта", 404

        # Преобразуем данные для Excel
        data = []
        for ticket in all_tickets:
            corrections_count = len(ticket.get('corrections_history', []))
            analyses_count = len(ticket.get('analyses_history', []))

            # Форматируем историю корректировок в текстовый вид
            corrections_text = ""
            if ticket.get('corrections_history'):
                for i, correction in enumerate(ticket['corrections_history'], 1):
                    corrections_text += f"{i}. {correction.get('timestamp', '')[:16]} - {correction.get('user', '')}: {correction.get('note', '')}\n"

            # Форматируем историю анализов в текстовый вид
            analyses_text = ""
            if ticket.get('analyses_history'):
                for i, analysis in enumerate(ticket['analyses_history'], 1):
                    result = "Допущен" if analysis.get('result') == 'approved' else "Отклонен"
                    analyses_text += f"{i}. {analysis.get('timestamp', '')[:16]} - {analysis.get('user', '')}: {result} - {analysis.get('details', '')}\n"

            # Конвертируем время в МСК
            created_at_msk = ""
            if ticket.get('created_at'):
                created_dt = datetime.fromisoformat(ticket['created_at'])
                created_at_msk = format_msk_time(created_dt)

            completed_at_msk = ""
            if ticket.get('completed_at'):
                completed_dt = datetime.fromisoformat(ticket['completed_at'])
                completed_at_msk = format_msk_time(completed_dt)

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
                'Количество_корректировок': corrections_count,
                'История_корректировок': corrections_text,
                'Количество_анализов': analyses_count,
                'История_анализов': analyses_text,
                'Время_производства_мин': ticket.get('total_production_time_minutes', ''),
                'Общее_время_производства': format_time_elapsed(ticket.get('total_production_time_minutes', 0)) if ticket.get('total_production_time_minutes') else ''
            }
            data.append(row)

        # Создаем DataFrame
        df = pd.DataFrame(data)

        # Создаем Excel файл с временем МСК в названии
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Тикеты', index=False)

            # Настраиваем ширину колонок для лучшего отображения
            worksheet = writer.sheets['Тикеты']
            worksheet.column_dimensions['A'].width = 15  # ID_тикета
            worksheet.column_dimensions['B'].width = 20  # Дата_создания_МСК
            worksheet.column_dimensions['C'].width = 20  # Дата_завершения_МСК
            worksheet.column_dimensions['D'].width = 15  # Продукт
            worksheet.column_dimensions['E'].width = 15  # Бренд
            worksheet.column_dimensions['F'].width = 20  # Технология
            worksheet.column_dimensions['G'].width = 15  # Миксер
            worksheet.column_dimensions['H'].width = 20  # Статус
            worksheet.column_dimensions['I'].width = 20  # Текущий_шаг
            worksheet.column_dimensions['J'].width = 15  # Пользователь
            worksheet.column_dimensions['K'].width = 10  # Количество_корректировок
            worksheet.column_dimensions['L'].width = 50  # История_корректировок
            worksheet.column_dimensions['M'].width = 10  # Количество_анализов
            worksheet.column_dimensions['N'].width = 50  # История_анализов
            worksheet.column_dimensions['O'].width = 15  # Время_производства_мин
            worksheet.column_dimensions['P'].width = 20  # Общее_время_производства

        output.seek(0)

        # Используем время МСК для названия файла
        msk_now = get_msk_time()
        filename = f'production_tickets_{msk_now.strftime("%d-%m-%Y_%H-%M")}_MSK.xlsx'

        return Response(
            output.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment;filename={filename}"}
        )

    except Exception as e:
        print(f"Ошибка при экспорте: {e}")
        return f"Ошибка при экспорте: {str(e)}", 500

# Админские функции
@app.route('/admin/clear_tickets', methods=['POST'])
def clear_tickets():
    """Очистка всех тикетов"""
    try:
        password = request.form.get('password', '')

        if password != '654321':
            return jsonify({'success': False, 'message': 'Неверный пароль'})

        # Очищаем базу
        db._save_tickets([])

        print("База тикетов очищена через веб-интерфейс")
        return jsonify({'success': True, 'message': 'Все тикеты успешно удалены'})

    except Exception as e:
        print(f"Ошибка при очистке тикетов: {e}")
        return jsonify({'success': False, 'message': f'Ошибка: {str(e)}'})

@app.route('/admin/backup', methods=['POST'])
def backup_tickets():
    """Создание резервной копии"""
    try:
        tickets = db._load_tickets()
        archive = db._load_archive()
        backup_data = {
            'backup_time': datetime.now().isoformat(),
            'active_records': len(tickets),
            'archive_records': len(archive),
            'active_data': tickets,
            'archive_data': archive
        }

        backup_filename = f'backup_tickets_{datetime.now().strftime("%Y-%m-%d_%H-%M")}.json'
        backup_path = os.path.join(os.path.dirname(__file__), backup_filename)

        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)

        return jsonify({'success': True, 'message': f'Резервная копия создана: {backup_filename}'})

    except Exception as e:
        return jsonify({'success': False, 'message': f'Ошибка: {str(e)}'})

@app.route('/admin/close_ticket/<ticket_id>', methods=['POST'])
def close_ticket(ticket_id):
    """Принудительное закрытие тикета"""
    try:
        ticket = db.get_ticket(ticket_id)
        if not ticket:
            return jsonify({'success': False, 'message': 'Тикет не найден'})

        db.update_ticket(ticket_id, {
            'status': 'completed',
            'current_step': 'manually_closed',
            'action': 'admin_forced_close'
        })

        return jsonify({'success': True, 'message': f'Тикет {ticket_id} закрыт'})

    except Exception as e:
        return jsonify({'success': False, 'message': f'Ошибка: {str(e)}'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)