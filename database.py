import json
import os
from typing import List, Dict, Any
from datetime import datetime, timedelta
from config import PRODUCT_MIXERS

class Database:
    def __init__(self, db_path: str = "tickets.json", archive_path: str = "archive_tickets.json"):
        self.db_path = db_path
        self.archive_path = archive_path
        self._ensure_db_exists()

    def _ensure_db_exists(self):
        """Создает файлы базы данных если их нет"""
        if not os.path.exists(self.db_path):
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump([], f)
        
        if not os.path.exists(self.archive_path):
            with open(self.archive_path, 'w', encoding='utf-8') as f:
                json.dump([], f)

    def _load_tickets(self) -> List[Dict[str, Any]]:
        """Загружает все активные тикеты из файла"""
        try:
            with open(self.db_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _load_archive(self) -> List[Dict[str, Any]]:
        """Загружает архив завершенных тикетов"""
        try:
            with open(self.archive_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_tickets(self, tickets: List[Dict[str, Any]]):
        """Сохраняет активные тикеты в файл"""
        with open(self.db_path, 'w', encoding='utf-8') as f:
            json.dump(tickets, f, ensure_ascii=False, indent=2)

    def _save_archive(self, archive: List[Dict[str, Any]]):
        """Сохраняет архив тикетов"""
        with open(self.archive_path, 'w', encoding='utf-8') as f:
            json.dump(archive, f, ensure_ascii=False, indent=2)

    def create_ticket(self, ticket_data: Dict[str, Any]) -> str:
        """Создает новый тикет"""
        tickets = self._load_tickets()
        
        # Проверяем, свободен ли миксер
        mixer = ticket_data['mixer']
        if self.is_mixer_busy(mixer):
            raise ValueError(f"Миксер {mixer} уже занят другим тикетом")
        
        # Генерируем ID тикета
        ticket_id = self._generate_ticket_id()
        
        # Инициализируем историю анализов и корректировок
        ticket_data['ticket_id'] = ticket_id
        ticket_data['created_at'] = datetime.now().isoformat()
        ticket_data['status'] = 'production_started'
        ticket_data['current_step'] = 'awaiting_sample'
        ticket_data['analyses_history'] = []  # История анализов
        ticket_data['corrections_history'] = []  # История корректировок
        ticket_data['history'] = [{
            'action': 'ticket_created',
            'timestamp': datetime.now().isoformat(),
            'user': ticket_data.get('username', 'unknown')
        }]
        
        tickets.append(ticket_data)
        self._save_tickets(tickets)
        return ticket_id

    def _generate_ticket_id(self) -> str:
        """Генерирует уникальный ID тикета"""
        tickets = self._load_tickets()
        archive = self._load_archive()
        return f"TK{len(tickets) + len(archive) + 1:04d}"

    def is_mixer_busy(self, mixer: str) -> bool:
        """Проверяет, занят ли миксер"""
        tickets = self._load_tickets()
        active_tickets = [t for t in tickets if t.get('status') not in ['completed', 'cancelled']]
        return any(t['mixer'] == mixer for t in active_tickets)

    def get_ticket(self, ticket_id: str) -> Dict[str, Any]:
        """Возвращает тикет по ID (сначала ищет в активных, потом в архиве)"""
        tickets = self._load_tickets()
        for ticket in tickets:
            if ticket.get('ticket_id') == ticket_id:
                return ticket
        
        # Если не нашли в активных, ищем в архиве
        archive = self._load_archive()
        for ticket in archive:
            if ticket.get('ticket_id') == ticket_id:
                return ticket
        return None

    def update_ticket(self, ticket_id: str, updates: Dict[str, Any]):
        """Обновляет тикет"""
        tickets = self._load_tickets()
        for i, ticket in enumerate(tickets):
            if ticket.get('ticket_id') == ticket_id:
                # Сохраняем историю действий
                if 'history' not in ticket:
                    ticket['history'] = []
                
                ticket['history'].append({
                    'action': updates.get('action', 'status_changed'),
                    'timestamp': datetime.now().isoformat(),
                    'user': updates.get('username', 'unknown'),
                    'details': updates.get('details', '')
                })

                # Сохраняем анализ если есть результат
                if updates.get('action') == 'analysis_approved':
                    if 'analyses_history' not in ticket:
                        ticket['analyses_history'] = []
                    
                    ticket['analyses_history'].append({
                        'timestamp': datetime.now().isoformat(),
                        'user': updates.get('username', 'unknown'),
                        'result': 'approved',
                        'details': 'Продукт допущен в производство',
                        'analysis_number': len(ticket.get('analyses_history', [])) + 1
                    })

                # Сохраняем корректировку если есть
                if updates.get('action') == 'correction_required' and updates.get('correction_note'):
                    if 'corrections_history' not in ticket:
                        ticket['corrections_history'] = []
                    
                    ticket['corrections_history'].append({
                        'timestamp': datetime.now().isoformat(),
                        'user': updates.get('username', 'unknown'),
                        'note': updates.get('correction_note'),
                        'analysis_number': len(ticket.get('analyses_history', [])) + 1
                    })
                
                # Если тикет завершен, перемещаем в архив
                if updates.get('status') == 'completed':
                    self._move_to_archive(ticket)
                    tickets.pop(i)
                else:
                    # Обновляем поля
                    ticket.update(updates)
                
                self._save_tickets(tickets)
                return True
        return False

    def _move_to_archive(self, ticket: Dict[str, Any]):
        """Перемещает тикет в архив"""
        archive = self._load_archive()
        ticket['completed_at'] = datetime.now().isoformat()
        
        # Рассчитываем общее время производства
        created_at = datetime.fromisoformat(ticket['created_at'])
        completed_at = datetime.fromisoformat(ticket['completed_at'])
        total_time = completed_at - created_at
        ticket['total_production_time_minutes'] = int(total_time.total_seconds() / 60)
        
        archive.append(ticket)
        self._save_archive(archive)

    def get_active_tickets(self) -> List[Dict[str, Any]]:
        """Возвращает активные тикеты"""
        tickets = self._load_tickets()
        return [t for t in tickets if t.get('status') not in ['completed', 'cancelled']]

    def get_tickets_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Возвращает тикеты по статусу"""
        tickets = self._load_tickets()
        return [t for t in tickets if t.get('status') == status]

    def get_production_tickets(self) -> List[Dict[str, Any]]:
        """Возвращает тикеты для производства"""
        tickets = self._load_tickets()
        return [t for t in tickets if t.get('status') in [
            'production_started', 'awaiting_sample', 'correction_required', 'awaiting_discharge'
        ]]

    def get_lab_tickets(self) -> List[Dict[str, Any]]:
        """Возвращает тикеты для лаборатории"""
        tickets = self._load_tickets()
        return [t for t in tickets if t.get('status') in [
            'sample_sent', 'sample_received', 'analysis_in_progress'
        ]]

    def get_mixer_status(self) -> Dict[str, Any]:
        """Возвращает статус всех миксеров"""
        tickets = self._load_tickets()
        active_tickets = self.get_active_tickets()
        
        status = {}
        # Все миксеры из конфига
        all_mixers = set()
        for mixers in PRODUCT_MIXERS.values():
            all_mixers.update(mixers)
        
        for mixer in sorted(all_mixers):
            mixer_tickets = [t for t in active_tickets if t.get('mixer') == f"Миксер_{mixer}"]
            if mixer_tickets:
                ticket = mixer_tickets[0]
                
                # Рассчитываем общее время с начала производства
                created_at = datetime.fromisoformat(ticket['created_at'])
                now = datetime.now()
                total_time = now - created_at
                total_minutes = int(total_time.total_seconds() / 60)
                
                status[f"Миксер_{mixer}"] = {
                    'ticket_id': ticket.get('ticket_id'),
                    'status': ticket.get('status'),
                    'product': ticket.get('product'),
                    'current_step': ticket.get('current_step'),
                    'total_time_minutes': total_minutes
                }
            else:
                status[f"Миксер_{mixer}"] = {'status': 'free'}
        
        return status