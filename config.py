BOT_TOKEN = "8226797646:AAGB5U2McefMyn9aP4MosGP1Qn9eB-YYBck"
GROUP_ID = -4985884553

# Настройки смен
DAY_SHIFT_START = 7  # 07:00
NIGHT_SHIFT_START = 19  # 19:00

# Московское время (UTC+3)
MSK_TIMEZONE_OFFSET = 3

# Таймауты в минутах
PRODUCTION_TIMEOUT = 70  # 70 минут на отбор пробы
LAB_TIMEOUT = 40  # 40 минут на анализ

# Доступные миксеры по продуктам
PRODUCT_MIXERS = {
    "Гель": [4, 5, 8, 9, 10, 11, 12, 13, 14],
    "Посуда": [1, 2, 3, 4, 5, 6, 7, 8],
    "АШ": [9, 10, 11, 12, 13, 14],
    "Кондиционер": [10]
}

# Бренды
BRANDS = ["AOS", "Sorti", "Биолан", "Фритайм", "Без названия"]