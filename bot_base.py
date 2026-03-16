import asyncio
import os
import asyncpg
import math
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

load_dotenv()

# ID администратора (ваш Telegram ID)
ADMIN_IDS = [5391827881]  # ⚠️ ЗАМЕНИТЕ НА ВАШ TELEGRAM ID!

# Функция для удаления старых сообщений
async def delete_old_messages(chat_id: int, current_message_id: int):
    """Удаляет все сообщения в чате, кроме текущего"""
    try:
        deleted_count = 0
        return 0
    except Exception as e:
        print(f"Ошибка при удалении: {e}")
        return 0

# Состояния для FSM
class Form(StatesGroup):
    add_name = State()
    add_article = State()
    add_description = State()
    add_quantity = State()
    add_warehouse = State()
    edit_quantity_search = State()
    edit_quantity_select = State()
    edit_quantity_warehouse = State()
    edit_quantity_new = State()
    check_stock_search = State()
    check_stock_select = State()
    move_search = State()
    move_select = State()
    move_quantity = State()
    move_from = State()
    move_to = State()
    list_search = State()
    # Состояния для админ-панели
    admin_add_user = State()
    admin_remove_user = State()
    admin_reply_request = State()
    admin_demote = State()
    admin_make_admin = State()
    # Состояния для калькулятора
    calc_repair_type = State()
    calc_part_cost = State()
    calc_services = State()
    # Состояния для удаления запчасти
    delete_item_search = State()
    delete_item_confirm = State()
    # Состояния для калькулятора аутсорса
    outsourcing_cost = State()

# Настройки БД
DB_CONFIG = {
    'host': os.getenv('DB_HOST', ''),
    'port': int(os.getenv('DB_PORT', )),
    'user': os.getenv('DB_USER', os.getenv('USER', '')),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'zapchasti_bot')
}

class Database:
    def __init__(self):
        self.pool = None
    
    async def create_pool(self):
        """Создаем пул соединений"""
        try:
            print(f"🔌 Подключаюсь к базе: {DB_CONFIG['database']}")
            print(f"📊 Параметры подключения: host={DB_CONFIG['host']}, user={DB_CONFIG['user']}")
            
            self.pool = await asyncpg.create_pool(
                **DB_CONFIG,
                min_size=1,
                max_size=10,
                command_timeout=60
            )
            
            # Создаем таблицу пользователей, если её нет
            await self.create_users_table()
            
            # Проверим, есть ли таблицы
            async with self.pool.acquire() as conn:
                tables = await conn.fetch("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema='public'
                """)
                print(f"📋 Таблицы в базе: {[t['table_name'] for t in tables]}")
                
                # Проверим количество записей
                try:
                    count = await conn.fetchval("SELECT COUNT(*) FROM items")
                    print(f"🔢 Количество запчастей: {count}")
                except:
                    print("📭 Таблица items еще не создана")
            
            print("✅ Подключение к БД установлено")
            
            # Обновляем названия складов при запуске
            await self.update_warehouses()
            return True
        except Exception as e:
            print(f"❌ Ошибка подключения к БД: {e}")
            return False
    
    async def create_users_table(self):
        """Создает таблицу пользователей, если её нет"""
        try:
            await self.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT UNIQUE NOT NULL,
                    username VARCHAR(255),
                    first_name VARCHAR(255),
                    last_name VARCHAR(255),
                    role VARCHAR(50) DEFAULT 'pending',  -- pending, user, admin
                    added_by BIGINT,
                    request_message TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            print("✅ Таблица users проверена/создана")
        except Exception as e:
            print(f"❌ Ошибка при создании таблицы users: {e}")
    
    async def is_admin(self, user_id: int) -> bool:
        """Проверяет, является ли пользователь администратором"""
        # Проверяем в списке ADMIN_IDS
        if user_id in ADMIN_IDS:
            return True
        
        # Проверяем в базе данных
        try:
            user = await self.fetchrow("SELECT role FROM users WHERE user_id = $1", user_id)
            return user is not None and user['role'] == 'admin'
        except Exception as e:
            print(f"Ошибка при проверке администратора: {e}")
            return False
    
    async def can_use_bot(self, user_id: int) -> bool:
        """Проверяет, может ли пользователь использовать бота"""
        # Администраторы могут всё
        if await self.is_admin(user_id):
            return True
        
        # Проверяем, есть ли пользователь в базе с ролью user
        try:
            user = await self.fetchrow("SELECT role FROM users WHERE user_id = $1", user_id)
            return user and user['role'] == 'user'
        except:
            return False
    
    async def get_user_status(self, user_id: int) -> str:
        """Получает статус пользователя"""
        try:
            user = await self.fetchrow("SELECT role FROM users WHERE user_id = $1", user_id)
            return user['role'] if user else 'not_found'
        except:
            return 'not_found'
    
    async def add_or_update_user(self, user_id: int, username: str, first_name: str, last_name: str):
        """Добавляет или обновляет пользователя"""
        try:
            # Проверяем, существует ли пользователь
            existing = await self.fetchrow("SELECT role FROM users WHERE user_id = $1", user_id)
            
            if existing:
                # Если пользователь уже есть, обновляем только данные, роль не меняем
                await self.execute("""
                    UPDATE users 
                    SET username = $2, first_name = $3, last_name = $4
                    WHERE user_id = $1
                """, user_id, username, first_name, last_name)
            else:
                # Если пользователя нет, добавляем с ролью pending
                await self.execute("""
                    INSERT INTO users (user_id, username, first_name, last_name, role)
                    VALUES ($1, $2, $3, $4, 'pending')
                """, user_id, username, first_name, last_name)
            return True
        except Exception as e:
            print(f"Ошибка при добавлении пользователя: {e}")
            return False
    
    async def approve_user(self, user_id: int, approved_by: int):
        """Одобряет доступ пользователю"""
        try:
            await self.execute("""
                UPDATE users 
                SET role = 'user', added_by = $2
                WHERE user_id = $1
            """, user_id, approved_by)
            return True
        except Exception as e:
            print(f"Ошибка при одобрении пользователя: {e}")
            return False
    
    async def reject_user(self, user_id: int):
        """Отклоняет доступ пользователю (удаляет из базы)"""
        try:
            await self.execute("DELETE FROM users WHERE user_id = $1 AND role = 'pending'", user_id)
            return True
        except Exception as e:
            print(f"Ошибка при отклонении пользователя: {e}")
            return False
    
    async def remove_user(self, user_id: int):
        """Удаляет пользователя из базы"""
        try:
            await self.execute("DELETE FROM users WHERE user_id = $1", user_id)
            return True
        except Exception as e:
            print(f"Ошибка при удалении пользователя: {e}")
            return False
    
    async def get_pending_users(self):
        """Получает список пользователей, ожидающих подтверждения"""
        try:
            return await self.fetch("""
                SELECT user_id, username, first_name, last_name, created_at
                FROM users
                WHERE role = 'pending'
                ORDER BY created_at DESC
            """)
        except Exception as e:
            print(f"Ошибка при получении списка ожидающих: {e}")
            return []
    
    async def get_all_users(self):
        """Получает список всех пользователей"""
        try:
            return await self.fetch("""
                SELECT user_id, username, first_name, last_name, role, created_at, added_by
                FROM users
                ORDER BY 
                    CASE role 
                        WHEN 'admin' THEN 1
                        WHEN 'user' THEN 2
                        WHEN 'pending' THEN 3
                        ELSE 4
                    END,
                    created_at DESC
            """)
        except Exception as e:
            print(f"Ошибка при получении списка пользователей: {e}")
            return []
    
    async def make_admin(self, user_id: int):
        """Делает пользователя администратором"""
        try:
            await self.execute("UPDATE users SET role = 'admin' WHERE user_id = $1", user_id)
            return True
        except Exception as e:
            print(f"Ошибка при назначении администратора: {e}")
            return False
    
    async def update_warehouses(self):
        """Обновляем названия складов (без удаления)"""
        try:
            # Новые названия складов
            new_warehouses = ['1744', '1844', '1742', '1960']
            
            # Получаем текущие склады
            current = await self.fetch("SELECT id, name FROM warehouses ORDER BY id")
            
            if len(current) == 0:
                # Если складов нет, просто создаем
                for wh in new_warehouses:
                    await self.execute("INSERT INTO warehouses (name) VALUES ($1)", wh)
                print(f"✅ Склады созданы: {', '.join(new_warehouses)}")
            else:
                # Обновляем названия существующих складов
                for i, wh in enumerate(current):
                    if i < len(new_warehouses):
                        # Меняем название существующего склада
                        await self.execute(
                            "UPDATE warehouses SET name = $1 WHERE id = $2",
                            new_warehouses[i], wh['id']
                        )
                
                # Если новых складов больше, добавляем недостающие
                if len(new_warehouses) > len(current):
                    for i in range(len(current), len(new_warehouses)):
                        await self.execute(
                            "INSERT INTO warehouses (name) VALUES ($1)",
                            new_warehouses[i]
                        )
                
                print(f"✅ Склады обновлены: {', '.join(new_warehouses)}")
                
        except Exception as e:
            print(f"❌ Ошибка при обновлении складов: {e}")
    
    async def close(self):
        if self.pool:
            await self.pool.close()
            print("🔌 Соединение с БД закрыто")
    
    async def fetch(self, query, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)
    
    async def fetchrow(self, query, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)
    
    async def execute(self, query, *args):
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)

# ==================== КАЛЬКУЛЯТОР РЕМОНТА ====================
class RepairCalculator:
    """Калькулятор стоимости ремонта на основе формул из Google Sheets"""
    
    # Типы ремонта
    REPAIR_TYPES = {
        'display': 'Дисплей',
        'battery': 'Аккумулятор',
        'flex': 'Шлейф плата'
    }
    
    @staticmethod
    def calculate_base_cost(repair_type: str, part_cost: float) -> float:
        """
        Расчет базовой стоимости по формуле N3
        repair_type: тип ремонта ('display', 'battery', 'flex')
        part_cost: стоимость запчасти (D3)
        """
        if repair_type == 'display':
            return RepairCalculator._calculate_display(part_cost)
        elif repair_type == 'battery':
            return RepairCalculator._calculate_battery(part_cost)
        elif repair_type == 'flex':
            return RepairCalculator._calculate_flex(part_cost)
        else:
            raise ValueError(f"Неизвестный тип ремонта: {repair_type}")
    
    @staticmethod
    def _calculate_display(part_cost: float) -> float:
        """Расчет для дисплея"""
        if part_cost <= 400:
            return part_cost + 3800
        elif part_cost <= 800:
            return part_cost + 3800
        elif part_cost <= 1000:
            return part_cost + 3800
        elif part_cost <= 1200:
            return part_cost + 3800
        elif part_cost <= 1350:
            return part_cost + 3800
        elif part_cost <= 1500:
            return part_cost + 3800
        elif part_cost <= 2000:
            return part_cost + 3800
        elif part_cost <= 2300:
            return part_cost + 3800
        elif part_cost <= 2700:
            return part_cost + 3800
        elif part_cost <= 3200:
            return part_cost + 3800
        elif part_cost <= 5000:
            return part_cost * 2.2
        elif part_cost <= 7000:
            return part_cost * 2.1
        elif part_cost <= 8500:
            return part_cost * 2.0
        elif part_cost <= 9500:
            return part_cost * 1.9
        elif part_cost <= 15000:
            return part_cost * 1.8 - 10
        else:
            return part_cost * 1.6
    
    @staticmethod
    def _calculate_battery(part_cost: float) -> float:
        """Расчет для аккумулятора"""
        if part_cost <= 400:
            return part_cost + 3000
        elif part_cost <= 800:
            return part_cost + 3000
        elif part_cost <= 1000:
            return part_cost + 3000
        elif part_cost <= 1200:
            return part_cost + 3000
        elif part_cost <= 1350:
            return part_cost + 3000
        elif part_cost <= 1500:
            return part_cost + 3000
        elif part_cost <= 2000:
            return part_cost + 3000
        elif part_cost <= 2300:
            return part_cost * 2.6
        elif part_cost <= 2700:
            return part_cost * 2.5
        elif part_cost <= 3200:
            return part_cost * 2.4
        elif part_cost <= 5000:
            return part_cost * 2.3
        elif part_cost <= 7000:
            return part_cost * 2.2
        elif part_cost <= 8500:
            return part_cost * 2.1
        elif part_cost <= 9500:
            return part_cost * 2.0
        elif part_cost <= 15000:
            return part_cost * 1.9
        else:
            return part_cost * 1.8
    
    @staticmethod
    def _calculate_flex(part_cost: float) -> float:
        """Расчет для шлейф платы"""
        if part_cost <= 400:
            return part_cost + 2500
        elif part_cost <= 800:
            return part_cost + 2500
        elif part_cost <= 1000:
            return part_cost + 2500
        elif part_cost <= 1200:
            return part_cost + 2500
        elif part_cost <= 1350:
            return part_cost + 2500
        elif part_cost <= 1500:
            return part_cost + 2500
        elif part_cost <= 2000:
            return part_cost + 2500
        elif part_cost <= 2300:
            return part_cost * 2.5
        elif part_cost <= 2700:
            return part_cost * 2.4
        elif part_cost <= 3200:
            return part_cost * 2.3
        elif part_cost <= 5000:
            return part_cost * 2.2
        elif part_cost <= 7000:
            return part_cost * 2.1
        elif part_cost <= 8500:
            return part_cost * 2.0
        elif part_cost <= 9500:
            return part_cost * 1.9
        elif part_cost <= 15000:
            return part_cost * 1.8
        else:
            return part_cost * 1.8
    
    @staticmethod
    def calculate_bonus_coefficient(additional_services: list) -> float:
        """
        Расчет бонусного коэффициента по формуле N4
        additional_services: список дополнительных услуг (True/False)
        """
        # Считаем количество True значений
        true_count = sum(1 for service in additional_services if service)
        return 0.05 * true_count
    
    @staticmethod
    def calculate_final_price(repair_type: str, part_cost: float, additional_services: list) -> float:
        """
        Расчет финальной цены по формуле: =ОКРУГЛВВЕРХ(N3*N4+N3;-2)-10
        """
        # Базовая стоимость (N3)
        base_cost = RepairCalculator.calculate_base_cost(repair_type, part_cost)
        
        # Бонусный коэффициент (N4)
        bonus_coeff = RepairCalculator.calculate_bonus_coefficient(additional_services)
        
        # Финальный расчет: ОКРУГЛВВЕРХ(N3*N4+N3;-2)-10
        # N3*N4+N3 = base_cost * bonus_coeff + base_cost
        intermediate = base_cost * bonus_coeff + base_cost
        
        # Округляем вверх до сотен (второй аргумент -2 означает округление до сотен)
        rounded = math.ceil(intermediate / 100) * 100
        
        # Вычитаем 10
        final_price = rounded - 10
        
        return final_price

    # ==================== НОВЫЙ МЕТОД ДЛЯ АУТСОРСА ====================
    @staticmethod
    def calculate_outsourcing(part_cost: float) -> float:
        """
        Расчет стоимости аутсорса (упрощенная формула без учета типа ремонта)
        Формула: =ОКРУГЛВВЕРХ(базовая_цена;-2)-10
        """
        # Базовая стоимость по формуле
        if part_cost <= 400:
            base = part_cost + 2000
        elif part_cost <= 800:
            base = part_cost + 2000
        elif part_cost <= 1000:
            base = part_cost + 2000
        elif part_cost <= 1200:
            base = part_cost + 2000
        elif part_cost <= 1350:
            base = part_cost + 2000
        elif part_cost <= 1500:
            base = part_cost + 2000
        elif part_cost <= 2000:
            base = part_cost + 2000
        elif part_cost <= 2300:
            base = part_cost * 2.4
        elif part_cost <= 2700:
            base = part_cost * 2.3
        elif part_cost <= 3200:
            base = part_cost * 2.2
        elif part_cost <= 5000:
            base = part_cost * 2.1
        elif part_cost <= 7000:
            base = part_cost * 2.0
        elif part_cost <= 8500:
            base = part_cost * 1.9
        elif part_cost <= 9500:
            base = part_cost * 1.8
        elif part_cost <= 15000:
            base = part_cost * 1.7
        else:
            base = part_cost * 1.6
        
        # Округляем вверх до сотен и вычитаем 10
        rounded = math.ceil(base / 100) * 100
        final_price = rounded - 10
        
        return final_price

# Инициализация
db = Database()
storage = MemoryStorage()
bot = Bot(token='')  # ⚠️ ЗАМЕНИТЕ НА ВАШ ТОКЕН!
dp = Dispatcher(storage=storage)

# Хранилище выбранных услуг для калькулятора
user_services = {}

# Middleware для проверки доступа
@dp.message.middleware()
@dp.callback_query.middleware()
async def access_middleware(handler, event, data):
    """Проверяет, имеет ли пользователь доступ к боту"""
    user_id = event.from_user.id
    
    # Пропускаем команду /start (она должна работать для всех)
    if isinstance(event, Message) and event.text and event.text.startswith('/start'):
        return await handler(event, data)
    
    # Проверяем доступ
    if await db.can_use_bot(user_id):
        return await handler(event, data)
    else:
        status = await db.get_user_status(user_id)
        
        if status == 'pending':
            text = "⏳ Ваш запрос на доступ отправлен администратору. Ожидайте подтверждения."
        else:
            text = "❌ У вас нет доступа к этому боту.\nНажмите /start чтобы отправить запрос администратору."
        
        # Если нет доступа, отправляем сообщение
        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer("❌ Нет доступа", show_alert=True)
        return

# ==================== МЕНЮ "РАБОТА СО СКЛАДОМ" ====================

# Клавиатура главного меню с группировкой функций склада и аутсорсом
def get_main_keyboard(is_admin: bool = False):
    buttons = [
        [InlineKeyboardButton(text="💰 Калькулятор ремонта", callback_data="calculator")],
        [InlineKeyboardButton(text="📊 Расчет аутсорса", callback_data="outsourcing")],
        [InlineKeyboardButton(text="📦 Работа со складом", callback_data="warehouse_menu")],
        [InlineKeyboardButton(text="🗑️ Удалить старые сообщения", callback_data="delete_old")]
    ]
    
    # Добавляем кнопку админ-панели для администраторов
    if is_admin:
        buttons.append([InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Меню работы со складом (с кнопкой удаления для админов)
def get_warehouse_keyboard(is_admin: bool = False):
    buttons = [
        [InlineKeyboardButton(text="📦 Добавить запчасть", callback_data="add")],
        [InlineKeyboardButton(text="📋 Список запчастей", callback_data="list")],
        [InlineKeyboardButton(text="🔍 Проверить остатки", callback_data="check_stock")],
        [InlineKeyboardButton(text="✏️ Изменить количество", callback_data="edit_quantity")],
        [InlineKeyboardButton(text="🔄 Переместить", callback_data="move")],
    ]
    
    # Добавляем кнопку удаления только для администраторов
    if is_admin:
        buttons.append([InlineKeyboardButton(text="🗑️ Удалить запчасть", callback_data="delete_item")])
    
    buttons.append([InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="main_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.callback_query(F.data == "warehouse_menu")
async def warehouse_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    # Проверяем, имеет ли пользователь доступ
    if not await db.can_use_bot(user_id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    is_admin = await db.is_admin(user_id)
    
    await callback.message.edit_text(
        "📦 **Работа со складом**\n\n"
        "Выберите действие:",
        reply_markup=get_warehouse_keyboard(is_admin)
    )
    await callback.answer()

# ==================== УДАЛЕНИЕ ЗАПЧАСТИ ====================
@dp.callback_query(F.data == "delete_item")
async def delete_item_start(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    # Проверяем, является ли пользователь администратором
    if not await db.is_admin(user_id):
        await callback.answer("❌ Эта функция доступна только администраторам", show_alert=True)
        return
    
    await state.set_state(Form.delete_item_search)
    await callback.message.edit_text(
        "🗑️ **Удаление запчасти**\n\n"
        "Введите текст для поиска запчасти (можно часть названия или артикула):",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()

@dp.message(Form.delete_item_search)
async def delete_item_search(message: Message, state: FSMContext):
    query = message.text.strip()
    user_id = message.from_user.id
    is_admin = await db.is_admin(user_id)
    
    # Ищем по названию или артикулу
    items = await db.fetch("""
        SELECT id, name, article
        FROM items 
        WHERE name ILIKE $1 OR article ILIKE $1
        ORDER BY name
        LIMIT 20
    """, f'%{query}%')
    
    if not items:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Новый поиск", callback_data="delete_item")],
            [InlineKeyboardButton(text="◀️ Назад в меню склада", callback_data="warehouse_menu")]
        ])
        
        await message.answer(
            f"❌ Ничего не найдено по запросу: {query}",
            reply_markup=keyboard
        )
        await state.clear()
        return
    
    # Создаем клавиатуру с результатами поиска
    buttons = []
    for item in items:
        display_name = item['name'] if len(item['name']) <= 30 else item['name'][:27] + "..."
        buttons.append([InlineKeyboardButton(
            text=f"🗑️ {display_name} ({item['article']})",
            callback_data=f"confirm_delete_{item['id']}"
        )])
    
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="warehouse_menu")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    text = f"🔍 Найдено запчастей: {len(items)}\n\n"
    text += "Выберите запчасть для удаления:"
    
    await message.answer(
        text,
        reply_markup=keyboard
    )
    await state.update_data(items=items)
    await state.set_state(Form.delete_item_confirm)

@dp.callback_query(Form.delete_item_confirm, F.data.startswith("confirm_delete_"))
async def delete_item_confirm(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    # Проверяем, является ли пользователь администратором
    if not await db.is_admin(user_id):
        await callback.answer("❌ Эта функция доступна только администраторам", show_alert=True)
        return
    
    item_id = int(callback.data.split('_')[2])
    
    # Получаем информацию о запчасти
    item = await db.fetchrow("SELECT name, article FROM items WHERE id = $1", item_id)
    
    if not item:
        await callback.message.edit_text(
            "❌ Запчасть не найдена",
            reply_markup=get_warehouse_keyboard(True)
        )
        await state.clear()
        await callback.answer()
        return
    
    # Создаем клавиатуру для подтверждения
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"execute_delete_{item_id}"),
            InlineKeyboardButton(text="❌ Нет, отмена", callback_data="warehouse_menu")
        ]
    ])
    
    await callback.message.edit_text(
        f"🗑️ **Подтверждение удаления**\n\n"
        f"Вы действительно хотите удалить запчасть?\n\n"
        f"📦 Название: {item['name']}\n"
        f"🏷 Артикул: {item['article']}",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("execute_delete_"))
async def execute_delete(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    # Проверяем, является ли пользователь администратором
    if not await db.is_admin(user_id):
        await callback.answer("❌ Эта функция доступна только администраторам", show_alert=True)
        return
    
    item_id = int(callback.data.split('_')[2])
    
    # Получаем информацию о запчасти для уведомления
    item = await db.fetchrow("SELECT name, article FROM items WHERE id = $1", item_id)
    
    if not item:
        await callback.message.edit_text(
            "❌ Запчасть не найдена",
            reply_markup=get_warehouse_keyboard(True)
        )
        await state.clear()
        await callback.answer()
        return
    
    try:
        # Начинаем транзакцию для безопасного удаления
        async with db.pool.acquire() as conn:
            async with conn.transaction():
                # Сначала удаляем все связанные записи из movements
                await conn.execute("DELETE FROM movements WHERE item_id = $1", item_id)
                
                # Затем удаляем запчасть
                await conn.execute("DELETE FROM items WHERE id = $1", item_id)
        
        await callback.message.edit_text(
            f"✅ Запчасть успешно удалена!\n\n"
            f"📦 Название: {item['name']}\n"
            f"🏷 Артикул: {item['article']}",
            reply_markup=get_warehouse_keyboard(True)
        )
    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка при удалении: {e}",
            reply_markup=get_warehouse_keyboard(True)
        )
    
    await state.clear()
    await callback.answer()

# ==================== КАЛЬКУЛЯТОР АУТСОРСА ====================
@dp.callback_query(F.data == "outsourcing")
async def outsourcing_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.outsourcing_cost)
    await callback.message.edit_text(
        "📊 **Расчет стоимости аутсорса**\n\n"
        "Введите стоимость запчасти (в рублях):",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()

@dp.message(Form.outsourcing_cost)
async def outsourcing_calculate(message: Message, state: FSMContext):
    try:
        part_cost = float(message.text.replace(',', '.'))
        
        # Рассчитываем стоимость
        final_price = RepairCalculator.calculate_outsourcing(part_cost)
        
        # Показываем детальный расчет
        # Базовая стоимость для отображения
        if part_cost <= 400:
            base = part_cost + 2000
            formula = f"{part_cost} + 2000"
        elif part_cost <= 800:
            base = part_cost + 2000
            formula = f"{part_cost} + 2000"
        elif part_cost <= 1000:
            base = part_cost + 2000
            formula = f"{part_cost} + 2000"
        elif part_cost <= 1200:
            base = part_cost + 2000
            formula = f"{part_cost} + 2000"
        elif part_cost <= 1350:
            base = part_cost + 2000
            formula = f"{part_cost} + 2000"
        elif part_cost <= 1500:
            base = part_cost + 2000
            formula = f"{part_cost} + 2000"
        elif part_cost <= 2000:
            base = part_cost + 2000
            formula = f"{part_cost} + 2000"
        elif part_cost <= 2300:
            base = part_cost * 2.4
            formula = f"{part_cost} × 2.4"
        elif part_cost <= 2700:
            base = part_cost * 2.3
            formula = f"{part_cost} × 2.3"
        elif part_cost <= 3200:
            base = part_cost * 2.2
            formula = f"{part_cost} × 2.2"
        elif part_cost <= 5000:
            base = part_cost * 2.1
            formula = f"{part_cost} × 2.1"
        elif part_cost <= 7000:
            base = part_cost * 2.0
            formula = f"{part_cost} × 2.0"
        elif part_cost <= 8500:
            base = part_cost * 1.9
            formula = f"{part_cost} × 1.9"
        elif part_cost <= 9500:
            base = part_cost * 1.8
            formula = f"{part_cost} × 1.8"
        elif part_cost <= 15000:
            base = part_cost * 1.7
            formula = f"{part_cost} × 1.7"
        else:
            base = part_cost * 1.6
            formula = f"{part_cost} × 1.6"
        
        rounded = math.ceil(base / 100) * 100
        
        result = f"📊 **Расчет стоимости аутсорса**\n\n"
        result += f"💰 Стоимость запчасти: {part_cost:,.0f} руб.\n\n"
        result += f"📈 **Детали расчета:**\n"
        result += f"• Базовая стоимость: {formula} = {base:,.0f} руб.\n"
        result += f"• Округление вверх до сотен: {rounded:,.0f} руб.\n"
        result += f"• Вычитание 10 руб.\n\n"
        result += f"💯 **ИТОГО: {final_price:,.0f} руб.**"
        
        is_admin = await db.is_admin(message.from_user.id)
        await message.answer(
            result,
            reply_markup=get_main_keyboard(is_admin)
        )
        await state.clear()
        
    except ValueError:
        await message.answer(
            "❌ Введите корректную стоимость (число)",
            reply_markup=get_cancel_keyboard()
        )
    except Exception as e:
        is_admin = await db.is_admin(message.from_user.id)
        await message.answer(
            f"❌ Ошибка расчета: {e}",
            reply_markup=get_main_keyboard(is_admin)
        )
        await state.clear()

# ==================== ОСТАЛЬНЫЕ ОБРАБОТЧИКИ (БЕЗ ИЗМЕНЕНИЙ) ====================
# Клавиатура админ-панели
def get_admin_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Запросы на доступ", callback_data="admin_pending")],
        [InlineKeyboardButton(text="👥 Все пользователи", callback_data="admin_list_users")],
        [InlineKeyboardButton(text="➕ Добавить пользователя", callback_data="admin_add_user")],
        [InlineKeyboardButton(text="➖ Удалить пользователя", callback_data="admin_remove_user")],
        [InlineKeyboardButton(text="👑 Назначить администратора", callback_data="admin_make_admin")],
        [InlineKeyboardButton(text="⬇️ Понизить администратора", callback_data="admin_demote_admin")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="main_menu")]
    ])
    return keyboard

# Клавиатура для обработки запросов
def get_request_keyboard(user_id: int):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_{user_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{user_id}")
        ]
    ])
    return keyboard

# Клавиатура для результатов поиска
def get_search_results_keyboard(items: list, action: str):
    buttons = []
    for item in items[:10]:  # Показываем первые 10 результатов
        # Обрезаем длинные названия
        display_name = item['name'] if len(item['name']) <= 30 else item['name'][:27] + "..."
        buttons.append([InlineKeyboardButton(
            text=f"{display_name} ({item['article']})",
            callback_data=f"{action}_{item['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Клавиатура для отмены
def get_cancel_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])
    return keyboard

# Клавиатура со складами
async def get_warehouses_keyboard(action="from"):
    warehouses = await db.fetch("SELECT id, name FROM warehouses ORDER BY name")
    buttons = []
    for wh in warehouses:
        callback_data = f"{action}_{wh['id']}_{wh['name']}"
        buttons.append([InlineKeyboardButton(
            text=wh['name'], 
            callback_data=callback_data
        )])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Вспомогательная функция для показа админ-панели
async def show_admin_panel(message: Message):
    """Показывает админ-панель"""
    await message.answer(
        "👑 Админ-панель\n\n"
        "Управление пользователями бота:",
        reply_markup=get_admin_keyboard()
    )

# Обработчик команды /start
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    is_admin = await db.is_admin(user_id)
    status = await db.get_user_status(user_id)
    
    # Отладочный вывод
    print(f"Пользователь {user_id} зашел в бот")
    print(f"Статус: {status}")
    print(f"Админ: {is_admin}")
    print(f"ADMIN_IDS: {ADMIN_IDS}")
    
    # Добавляем или обновляем пользователя
    await db.add_or_update_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name or ''
    )
    
    if is_admin:
        # Админ видит полное меню
        await message.answer(
            f"👋 Добро пожаловать, Администратор!\n\n"
            f"📦 Склады: 1744, 1844, 1742, 1960\n\n"
            f"Выберите действие:",
            reply_markup=get_main_keyboard(is_admin)
        )
    elif status == 'user':
        # Одобренный пользователь видит меню
        await message.answer(
            f"👋 Добро пожаловать!\n\n"
            f"📦 Склады: 1744, 1844, 1742, 1960\n\n"
            f"Выберите действие:",
            reply_markup=get_main_keyboard(is_admin)
        )
    elif status == 'pending':
        # Ожидающий подтверждения
        await message.answer(
            "⏳ Ваш запрос на доступ отправлен администратору.\n"
            "Вы получите уведомление, когда ваш доступ будет одобрен."
        )
        
        # Уведомляем всех администраторов о новом запросе
        admins = await db.fetch("SELECT user_id FROM users WHERE role = 'admin'")
        for admin in admins:
            try:
                await bot.send_message(
                    admin['user_id'],
                    f"🆕 Новый запрос на доступ!\n\n"
                    f"Пользователь: {message.from_user.first_name}\n"
                    f"Username: @{message.from_user.username if message.from_user.username else 'нет'}\n"
                    f"ID: {user_id}\n\n"
                    f"Выберите действие:",
                    reply_markup=get_request_keyboard(user_id)
                )
            except:
                pass
    else:
        # Новый пользователь
        await message.answer(
            "👋 Для получения доступа к боту отправьте запрос администратору.\n"
            "Нажмите кнопку ниже:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📨 Отправить запрос", callback_data="request_access")]
            ])
        )

# Команда для проверки статуса администратора
@dp.message(Command("check_admin"))
async def check_admin(message: Message):
    """Проверяет статус администратора (только для админов)"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для этой команды")
        return
    
    # Получаем ID пользователя из сообщения
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /check_admin <user_id>")
        return
    
    try:
        check_id = int(args[1])
        user = await db.fetchrow("SELECT * FROM users WHERE user_id = $1", check_id)
        
        if user:
            text = f"Информация о пользователе {check_id}:\n"
            text += f"Роль: {user['role']}\n"
            text += f"Имя: {user['first_name']}\n"
            text += f"Username: @{user['username'] if user['username'] else 'нет'}\n"
            text += f"Добавлен: {user['created_at']}"
        else:
            text = f"Пользователь {check_id} не найден в базе"
        
        await message.answer(text)
    except ValueError:
        await message.answer("❌ Введите корректный ID")

# Команда для проверки роли пользователя
@dp.message(Command("check_role"))
async def check_role(message: Message):
    """Проверяет роль пользователя в базе (только для админов)"""
    user_id = message.from_user.id
    
    if not await db.is_admin(user_id):
        await message.answer("❌ У вас нет прав для этой команды")
        return
    
    # Получаем ID пользователя из сообщения
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Использование: /check_role <user_id>")
        return
    
    try:
        check_id = int(args[1])
        user = await db.fetchrow("SELECT * FROM users WHERE user_id = $1", check_id)
        
        if user:
            text = f"📊 **Информация о пользователе {check_id}:**\n\n"
            text += f"Роль: `{user['role']}`\n"
            text += f"Имя: {user['first_name']}\n"
            text += f"Username: @{user['username'] if user['username'] else 'нет'}\n"
            text += f"Добавлен админом: {user['added_by'] if user['added_by'] else 'нет'}\n"
            text += f"Дата регистрации: {user['created_at'].strftime('%d.%m.%Y %H:%M')}"
        else:
            text = f"❌ Пользователь {check_id} не найден в базе"
        
        await message.answer(text)
    except ValueError:
        await message.answer("❌ Введите корректный ID")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.callback_query(F.data == "request_access")
async def request_access(callback: CallbackQuery):
    user_id = callback.from_user.id
    status = await db.get_user_status(user_id)
    
    if status == 'pending':
        await callback.answer("⏳ Ваш запрос уже отправлен!", show_alert=True)
        return
    
    # Обновляем статус на pending
    await db.add_or_update_user(
        user_id=user_id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
        last_name=callback.from_user.last_name or ''
    )
    
    await callback.message.edit_text(
        "✅ Запрос отправлен администратору!\n"
        "Ожидайте подтверждения."
    )
    
    # Уведомляем всех администраторов
    admins = await db.fetch("SELECT user_id FROM users WHERE role = 'admin'")
    for admin in admins:
        try:
            await bot.send_message(
                admin['user_id'],
                f"🆕 Новый запрос на доступ!\n\n"
                f"Пользователь: {callback.from_user.first_name}\n"
                f"Username: @{callback.from_user.username if callback.from_user.username else 'нет'}\n"
                f"ID: {user_id}\n\n"
                f"Выберите действие:",
                reply_markup=get_request_keyboard(user_id)
            )
        except:
            pass
    
    await callback.answer()

# Обработчик нажатий на кнопки
@dp.callback_query(F.data == "main_menu")
async def main_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    is_admin = await db.is_admin(user_id)
    
    await callback.message.edit_text(
        "👋 Выберите действие:",
        reply_markup=get_main_keyboard(is_admin)
    )
    await callback.answer()

@dp.callback_query(F.data == "cancel")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    is_admin = await db.is_admin(user_id)
    
    await callback.message.edit_text(
        "👋 Выберите действие:",
        reply_markup=get_main_keyboard(is_admin)
    )
    await callback.answer()

# ==================== КАЛЬКУЛЯТОР РЕМОНТА ====================
@dp.callback_query(F.data == "calculator")
async def calculator_start(callback: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Дисплей", callback_data="repair_display")],
        [InlineKeyboardButton(text="🔋 Аккумулятор", callback_data="repair_battery")],
        [InlineKeyboardButton(text="🔌 Шлейф плата", callback_data="repair_flex")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(
        "💰 **Калькулятор стоимости ремонта**\n\n"
        "Выберите тип ремонта:",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("repair_"))
async def repair_type_selected(callback: CallbackQuery, state: FSMContext):
    repair_type = callback.data.replace("repair_", "")
    
    await state.update_data(repair_type=repair_type)
    await state.set_state(Form.calc_part_cost)
    
    await callback.message.edit_text(
        f"💰 Введите стоимость запчасти (в рублях):\n\n"
        f"Тип ремонта: {RepairCalculator.REPAIR_TYPES[repair_type]}",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()

@dp.message(Form.calc_part_cost)
async def calc_part_cost(message: Message, state: FSMContext):
    try:
        part_cost = float(message.text.replace(',', '.'))
        
        await state.update_data(part_cost=part_cost)
        await state.set_state(Form.calc_services)
        
        # Клавиатура для дополнительных услуг
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬜ Сложность ремонта", callback_data="service_urgent")],
            [InlineKeyboardButton(text="⬜ Риски при ремонте", callback_data="service_diagnostic")],
            [InlineKeyboardButton(text="⬜ Оригинальная запчасть", callback_data="service_software")],
            [InlineKeyboardButton(text="💯 Рассчитать", callback_data="calculate_final")]
        ])
        
        await message.answer(
            "Выберите дополнительные услуги (можно несколько):\n"
            "После выбора нажмите 'Рассчитать'",
            reply_markup=keyboard
        )
        
    except ValueError:
        await message.answer(
            "❌ Введите корректную стоимость (число)",
            reply_markup=get_cancel_keyboard()
        )

@dp.callback_query(F.data.startswith("service_"))
async def toggle_service(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    service = callback.data.replace("service_", "")
    
    if user_id not in user_services:
        user_services[user_id] = []
    
    if service in user_services[user_id]:
        user_services[user_id].remove(service)
        new_text = "⬜"
    else:
        user_services[user_id].append(service)
        new_text = "✅"
    
    # Обновляем текст кнопки
    for row in callback.message.reply_markup.inline_keyboard:
        for button in row:
            if button.callback_data == callback.data:
                button.text = f"{new_text} {button.text[2:]}"
                break
    
    await callback.message.edit_reply_markup(reply_markup=callback.message.reply_markup)
    await callback.answer()

@dp.callback_query(F.data == "calculate_final")
async def calculate_final(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    
    # Получаем выбранные услуги
    services = user_services.get(user_id, [])
    
    # Преобразуем услуги в булевы значения для формулы
    service_bools = [
        'urgent' in services,
        'diagnostic' in services,
        'software' in services
    ]
    
    try:
        # Рассчитываем финальную цену
        final_price = RepairCalculator.calculate_final_price(
            data['repair_type'],
            data['part_cost'],
            service_bools
        )
        
        # Формируем отчет
        result = f"💰 **Расчет стоимости ремонта**\n\n"
        result += f"Тип: {RepairCalculator.REPAIR_TYPES[data['repair_type']]}\n"
        result += f"Стоимость запчасти: {data['part_cost']:,.0f} руб.\n"
        
        if services:
            service_names = []
            for s in services:
                if s == 'urgent':
                    service_names.append('Сложность ремонта')
                elif s == 'diagnostic':
                    service_names.append('Риски при ремонте')
                elif s == 'software':
                    service_names.append('Оригинальная запчасть')
            result += f"Доп. услуги: {', '.join(service_names)}\n"
        
        result += f"\n**ИТОГО: {final_price:,.0f} руб.**"
        
        # Очищаем временные данные
        if user_id in user_services:
            del user_services[user_id]
        
        await callback.message.edit_text(
            result,
            reply_markup=get_main_keyboard(await db.is_admin(user_id))
        )
        await state.clear()
        
    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка расчета: {e}",
            reply_markup=get_main_keyboard(await db.is_admin(user_id))
        )
        await state.clear()
    
    await callback.answer()

# ==================== АДМИН-ПАНЕЛЬ ====================
@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    # Проверяем, является ли пользователь администратором
    if not await db.is_admin(user_id):
        await callback.answer("❌ У вас нет прав администратора", show_alert=True)
        return
    
    await callback.message.edit_text(
        "👑 Админ-панель\n\n"
        "Управление пользователями бота:",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_pending")
async def admin_pending(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not await db.is_admin(user_id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    pending = await db.get_pending_users()
    
    if not pending:
        await callback.message.edit_text(
            "📭 Нет ожидающих запросов",
            reply_markup=get_admin_keyboard()
        )
        await callback.answer()
        return
    
    # Создаем клавиатуру с кнопками для каждого ожидающего пользователя
    buttons = []
    for user in pending[:5]:  # Показываем первые 5 запросов
        user_text = f"@{user['username']}" if user['username'] else f"{user['first_name']}"
        buttons.append([
            InlineKeyboardButton(
                text=f"✅ {user_text} (ID: {user['user_id']})",
                callback_data=f"approve_{user['user_id']}"
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                text=f"❌ Отклонить {user_text}",
                callback_data=f"reject_{user['user_id']}"
            )
        ])
    
    # Добавляем кнопку "Назад"
    buttons.append([InlineKeyboardButton(text="◀️ Назад в админ-панель", callback_data="admin_panel")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    text = "⏳ Ожидающие запросы на доступ:\n\n"
    for user in pending:
        text += f"• {user['first_name']} {user['last_name'] or ''}"
        if user['username']:
            text += f" (@{user['username']})\n"
        else:
            text += "\n"
        text += f"  ID: {user['user_id']}\n"
        text += f"  Запрос от: {user['created_at'].strftime('%d.%m.%Y %H:%M')}\n\n"
    
    # Разбиваем длинные сообщения
    if len(text) > 4000:
        text = text[:4000] + "...\n(показаны первые запросы)"
    
    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_list_users")
async def admin_list_users(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not await db.is_admin(user_id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    users = await db.get_all_users()
    
    if not users:
        await callback.message.edit_text(
            "📭 Список пользователей пуст",
            reply_markup=get_admin_keyboard()
        )
        await callback.answer()
        return
    
    text = "👥 Все пользователи:\n\n"
    for user in users:
        role_emoji = {
            'admin': '👑',
            'user': '✅',
            'pending': '⏳'
        }.get(user['role'], '👤')
        
        text += f"{role_emoji} ID: {user['user_id']}\n"
        if user['username']:
            text += f"  Username: @{user['username']}\n"
        text += f"  Имя: {user['first_name']} {user['last_name'] or ''}\n"
        text += f"  Роль: {user['role']}\n"
        if user['added_by']:
            text += f"  Добавлен админом: {user['added_by']}\n"
        text += f"  Дата: {user['created_at'].strftime('%d.%m.%Y')}\n\n"
    
    # Разбиваем длинные сообщения
    if len(text) > 4000:
        text = text[:4000] + "...\n(показаны первые пользователи)"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_add_user")
async def admin_add_user_start(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    if not await db.is_admin(user_id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(Form.admin_add_user)
    await callback.message.edit_text(
        "➕ Добавление пользователя\n\n"
        "Введите Telegram ID пользователя (число):\n"
        "Пользователь должен сначала написать боту /start",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()

@dp.message(Form.admin_add_user)
async def admin_add_user_process(message: Message, state: FSMContext):
    try:
        new_user_id = int(message.text.strip())
        
        # Проверяем, существует ли пользователь
        try:
            user_info = await bot.get_chat(new_user_id)
            
            # Добавляем пользователя как одобренного
            success = await db.approve_user(new_user_id, message.from_user.id)
            
            if success:
                await message.answer(
                    f"✅ Пользователь успешно добавлен!\n\n"
                    f"ID: {new_user_id}\n"
                    f"Имя: {user_info.first_name}\n"
                    f"Username: @{user_info.username if user_info.username else 'нет'}"
                )
                
                # Уведомляем пользователя
                try:
                    await bot.send_message(
                        new_user_id,
                        "✅ Вам открыт доступ к боту!\n"
                        "Нажмите /start чтобы начать работу."
                    )
                except:
                    pass
            else:
                await message.answer("❌ Ошибка при добавлении пользователя")
            
        except Exception as e:
            await message.answer(
                f"❌ Пользователь с ID {new_user_id} не найден.\n"
                "Убедитесь, что пользователь написал боту /start"
            )
        
        # Возвращаемся в админ-панель
        await state.clear()
        await show_admin_panel(message)
        
    except ValueError:
        await message.answer("❌ Введите корректный числовой ID")
        await state.clear()
        await show_admin_panel(message)

@dp.callback_query(F.data == "admin_remove_user")
async def admin_remove_user_start(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    if not await db.is_admin(user_id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(Form.admin_remove_user)
    await callback.message.edit_text(
        "➖ Удаление пользователя\n\n"
        "Введите Telegram ID пользователя для удаления:",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()

@dp.message(Form.admin_remove_user)
async def admin_remove_user_process(message: Message, state: FSMContext):
    try:
        remove_user_id = int(message.text.strip())
        
        # Не даем удалить самого себя
        if remove_user_id == message.from_user.id:
            await message.answer("❌ Нельзя удалить самого себя")
            await state.clear()
            await show_admin_panel(message)
            return
        
        # Проверяем, не админ ли это
        if await db.is_admin(remove_user_id) and remove_user_id not in ADMIN_IDS:
            await message.answer("❌ Нельзя удалить администратора")
            await state.clear()
            await show_admin_panel(message)
            return
        
        success = await db.remove_user(remove_user_id)
        
        if success:
            await message.answer(f"✅ Пользователь {remove_user_id} удален")
        else:
            await message.answer("❌ Пользователь не найден")
        
        # Возвращаемся в админ-панель
        await state.clear()
        await show_admin_panel(message)
        
    except ValueError:
        await message.answer("❌ Введите корректный числовой ID")
        await state.clear()
        await show_admin_panel(message)

@dp.callback_query(F.data == "admin_make_admin")
async def admin_make_admin_start(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    if not await db.is_admin(user_id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(Form.admin_make_admin)
    await callback.message.edit_text(
        "👑 Назначение администратора\n\n"
        "Введите Telegram ID пользователя, которого хотите сделать администратором:",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()

@dp.message(Form.admin_make_admin)
async def admin_make_admin_process(message: Message, state: FSMContext):
    try:
        new_admin_id = int(message.text.strip())
        
        # Проверяем, существует ли пользователь
        user = await db.fetchrow("SELECT * FROM users WHERE user_id = $1", new_admin_id)
        
        if not user:
            await message.answer(
                f"❌ Пользователь с ID {new_admin_id} не найден в базе.\n"
                "Сначала добавьте пользователя через /start"
            )
        else:
            # Назначаем администратором
            try:
                await db.execute("UPDATE users SET role = 'admin' WHERE user_id = $1", new_admin_id)
                await message.answer(f"✅ Пользователь {new_admin_id} теперь администратор")
                
                # Отправляем уведомление новому админу
                try:
                    await bot.send_message(
                        new_admin_id,
                        "👑 Вам назначены права администратора в боте учета запчастей!\n"
                        "Нажмите /start чтобы увидеть админ-панель."
                    )
                except:
                    pass
                    
            except Exception as e:
                await message.answer(f"❌ Ошибка при назначении: {e}")
        
        # Возвращаемся в админ-панель
        await state.clear()
        await show_admin_panel(message)
        
    except ValueError:
        await message.answer("❌ Введите корректный числовой ID")
        await state.clear()
        await show_admin_panel(message)

@dp.callback_query(F.data == "admin_demote_admin")
async def admin_demote_admin_start(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    if not await db.is_admin(user_id):
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    
    await state.set_state(Form.admin_demote)
    await callback.message.edit_text(
        "⬇️ Понижение администратора\n\n"
        "Введите Telegram ID администратора, которого хотите понизить до обычного пользователя:",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()

@dp.message(Form.admin_demote)
async def admin_demote_admin_process(message: Message, state: FSMContext):
    try:
        demote_user_id = int(message.text.strip())
        
        # Проверяем, не пытается ли админ понизить самого себя
        if demote_user_id == message.from_user.id:
            await message.answer("❌ Нельзя понизить самого себя")
            await state.clear()
            await show_admin_panel(message)
            return
        
        # Получаем информацию о пользователе
        user = await db.fetchrow("SELECT * FROM users WHERE user_id = $1", demote_user_id)
        
        if not user:
            await message.answer(f"❌ Пользователь с ID {demote_user_id} не найден в базе данных")
            await state.clear()
            await show_admin_panel(message)
            return
        
        # Проверяем, является ли пользователь администратором
        if user['role'] != 'admin':
            await message.answer(
                f"❌ Пользователь {demote_user_id} имеет роль '{user['role']}', не является администратором"
            )
            await state.clear()
            await show_admin_panel(message)
            return
        
        # Проверяем, не является ли пользователь главным администратором
        if demote_user_id in ADMIN_IDS:
            await message.answer("❌ Нельзя понизить главного администратора")
            await state.clear()
            await show_admin_panel(message)
            return
        
        # Понижаем администратора
        try:
            await db.execute("UPDATE users SET role = 'user' WHERE user_id = $1", demote_user_id)
            await message.answer(f"✅ Администратор {demote_user_id} понижен до пользователя")
            
            # Уведомляем пользователя о понижении
            try:
                await bot.send_message(
                    demote_user_id,
                    "⬇️ Ваши права администратора были отозваны.\n"
                    "Теперь вы обычный пользователь бота."
                )
            except:
                pass
                
        except Exception as e:
            await message.answer(f"❌ Ошибка при понижении: {e}")
        
        # Возвращаемся в админ-панель
        await state.clear()
        await show_admin_panel(message)
        
    except ValueError:
        await message.answer("❌ Введите корректный числовой ID")
        await state.clear()
        await show_admin_panel(message)

# Обновленные обработчики одобрения/отклонения с возвратом к списку
@dp.callback_query(F.data.startswith("approve_"))
async def approve_request(callback: CallbackQuery):
    admin_id = callback.from_user.id
    
    if not await db.is_admin(admin_id):
        await callback.answer("❌ Нет прав администратора", show_alert=True)
        return
    
    user_id = int(callback.data.split('_')[1])
    
    # Одобряем пользователя
    success = await db.approve_user(user_id, admin_id)
    
    if success:
        await callback.message.edit_text(
            f"✅ Пользователь {user_id} одобрен!"
        )
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                user_id,
                "✅ Ваш доступ к боту одобрен!\n"
                "Нажмите /start чтобы начать работу."
            )
        except:
            pass
        
        # Показываем обновленный список ожидающих
        await asyncio.sleep(1)
        await admin_pending(callback)
    else:
        await callback.message.edit_text("❌ Ошибка при одобрении")
    
    await callback.answer()

@dp.callback_query(F.data.startswith("reject_"))
async def reject_request(callback: CallbackQuery):
    admin_id = callback.from_user.id
    
    if not await db.is_admin(admin_id):
        await callback.answer("❌ Нет прав администратора", show_alert=True)
        return
    
    user_id = int(callback.data.split('_')[1])
    
    # Отклоняем пользователя
    success = await db.reject_user(user_id)
    
    if success:
        await callback.message.edit_text(
            f"❌ Пользователь {user_id} отклонен"
        )
        
        # Уведомляем пользователя
        try:
            await bot.send_message(
                user_id,
                "❌ Ваш запрос на доступ отклонен администратором."
            )
        except:
            pass
        
        # Показываем обновленный список ожидающих
        await asyncio.sleep(1)
        await admin_pending(callback)
    else:
        await callback.message.edit_text("❌ Ошибка при отклонении")
    
    await callback.answer()

# ==================== СПИСОК ЗАПЧАСТЕЙ ====================
@dp.callback_query(F.data == "list")
async def list_start(callback: CallbackQuery, state: FSMContext):
    try:
        # Получаем все запчасти
        items = await db.fetch("""
            SELECT i.id, i.name, i.article, i.description
            FROM items i
            ORDER BY i.name
            LIMIT 50
        """)
        
        if not items:
            is_admin = await db.is_admin(callback.from_user.id)
            await callback.message.edit_text(
                "📭 База запчастей пуста",
                reply_markup=get_main_keyboard(is_admin)
            )
            await callback.answer()
            return
        
        text = "📋 Все запчасти:\n\n"
        item_count = 0
        
        for item in items:
            item_count += 1
            text += f"🔹 {item['name']}\n"
            text += f"   🏷 Артикул: {item['article']}\n"
            
            # Получаем остатки по складам для этой запчасти
            stocks = await db.fetch("""
                SELECT w.name, s.quantity
                FROM stock s
                JOIN warehouses w ON s.warehouse_id = w.id
                WHERE s.item_id = $1 AND s.quantity > 0
                ORDER BY w.name
            """, item['id'])
            
            if stocks:
                total = 0
                for stock in stocks:
                    text += f"   📍 Склад {stock['name']}: {stock['quantity']} шт.\n"
                    total += stock['quantity']
                text += f"   📊 Всего: {total} шт.\n"
            else:
                text += f"   ❌ Нет в наличии\n"
            
            text += "\n"
            
            # Если текст слишком длинный, отправляем отдельным сообщением
            if len(text) > 3500 and item_count < len(items):
                await callback.message.answer(text)
                text = "📋 Продолжение списка:\n\n"
        
        # Клавиатура с кнопками Поиск и Назад
        is_admin = await db.is_admin(callback.from_user.id)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Поиск", callback_data="search_items")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
        ])
        
        if text:
            await callback.message.edit_text(
                text, 
                reply_markup=keyboard
            )
        else:
            await callback.message.answer(
                "📋 Список завершен",
                reply_markup=keyboard
            )
        await callback.answer()
        
    except Exception as e:
        is_admin = await db.is_admin(callback.from_user.id)
        await callback.message.edit_text(
            f"❌ Ошибка: {e}",
            reply_markup=get_main_keyboard(is_admin)
        )
        await callback.answer()

# ==================== ПОИСК ЗАПЧАСТЕЙ ====================
@dp.callback_query(F.data == "search_items")
async def search_items_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.list_search)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к списку", callback_data="list")]
    ])
    
    await callback.message.edit_text(
        "🔍 Поиск запчастей\n\n"
        "Введите текст для поиска (можно часть названия или артикула):",
        reply_markup=keyboard
    )
    await callback.answer()

@dp.message(Form.list_search)
async def search_items_result(message: Message, state: FSMContext):
    query = message.text.strip()
    
    # Ищем по названию или артикулу
    items = await db.fetch("""
        SELECT i.id, i.name, i.article, i.description
        FROM items i 
        WHERE i.name ILIKE $1 OR i.article ILIKE $1
        ORDER BY i.name
        LIMIT 50
    """, f'%{query}%')
    
    if not items:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Новый поиск", callback_data="search_items")],
            [InlineKeyboardButton(text="◀️ Назад к списку", callback_data="list")]
        ])
        
        await message.answer(
            f"❌ Ничего не найдено по запросу: {query}",
            reply_markup=keyboard
        )
        await state.clear()
        return
    
    text = f"🔍 Результаты поиска по запросу '{query}':\n\n"
    text += f"Найдено запчастей: {len(items)}\n\n"
    
    for item in items[:10]:  # Показываем первые 10
        text += f"🔹 {item['name']}\n"
        text += f"   🏷 Артикул: {item['article']}\n"
        
        # Получаем остатки по складам
        stocks = await db.fetch("""
            SELECT w.name, s.quantity
            FROM stock s
            JOIN warehouses w ON s.warehouse_id = w.id
            WHERE s.item_id = $1 AND s.quantity > 0
            ORDER BY w.name
        """, item['id'])
        
        if stocks:
            total = 0
            for stock in stocks:
                text += f"   📍 Склад {stock['name']}: {stock['quantity']} шт.\n"
                total += stock['quantity']
            text += f"   📊 Всего: {total} шт.\n"
        else:
            text += f"   ❌ Нет в наличии\n"
        text += "\n"
    
    if len(items) > 10:
        text += f"... и еще {len(items) - 10} запчастей\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Новый поиск", callback_data="search_items")],
        [InlineKeyboardButton(text="◀️ Назад к списку", callback_data="list")]
    ])
    
    await message.answer(
        text,
        reply_markup=keyboard
    )
    await state.clear()

# ==================== ПРОВЕРКА ОСТАТКОВ С ПОИСКОМ ====================
@dp.callback_query(F.data == "check_stock")
async def check_stock_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.check_stock_search)
    await callback.message.edit_text(
        "🔍 Проверка остатков\n\n"
        "Введите текст для поиска запчасти (можно часть названия или артикула):",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()

@dp.message(Form.check_stock_search)
async def check_stock_search(message: Message, state: FSMContext):
    query = message.text.strip()
    
    # Ищем по названию или артикулу
    items = await db.fetch("""
        SELECT id, name, article
        FROM items 
        WHERE name ILIKE $1 OR article ILIKE $1
        ORDER BY name
        LIMIT 20
    """, f'%{query}%')
    
    if not items:
        is_admin = await db.is_admin(message.from_user.id)
        await message.answer(
            f"❌ Ничего не найдено по запросу: {query}",
            reply_markup=get_main_keyboard(is_admin)
        )
        await state.clear()
        return
    
    # Показываем результаты поиска
    await message.answer(
        "🔍 Результаты поиска:\n\nВыберите запчасть:",
        reply_markup=get_search_results_keyboard(items, "check_stock_select")
    )
    await state.update_data(items=items)
    await state.set_state(Form.check_stock_select)

@dp.callback_query(Form.check_stock_select, F.data.startswith("check_stock_select_"))
async def check_stock_select(callback: CallbackQuery, state: FSMContext):
    item_id = int(callback.data.split('_')[3])
    
    item = await db.fetchrow("SELECT id, name, description, article FROM items WHERE id = $1", item_id)
    if not item:
        is_admin = await db.is_admin(callback.from_user.id)
        await callback.message.edit_text(
            "❌ Запчасть не найдена",
            reply_markup=get_main_keyboard(is_admin)
        )
        await state.clear()
        await callback.answer()
        return
    
    # Получаем остатки по всем складам
    stock = await db.fetch("""
        SELECT w.name, COALESCE(s.quantity, 0) as quantity
        FROM warehouses w
        LEFT JOIN stock s ON w.id = s.warehouse_id AND s.item_id = $1
        ORDER BY w.name
    """, item['id'])
    
    text = f"📦 {item['name']}\n"
    text += f"🏷 Артикул: {item['article']}\n"
    if item['description']:
        text += f"📝 Описание: {item['description']}\n"
    text += "\n📊 Остатки по складам:\n"
    
    total = 0
    for s in stock:
        if s['quantity'] > 0:
            text += f"✅ Склад {s['name']}: {s['quantity']} шт.\n"
            total += s['quantity']
        else:
            text += f"⬜ Склад {s['name']}: 0 шт.\n"
    
    text += f"\n🔢 ИТОГО: {total} шт."
    
    is_admin = await db.is_admin(callback.from_user.id)
    await callback.message.edit_text(
        text,
        reply_markup=get_main_keyboard(is_admin)
    )
    await state.clear()
    await callback.answer()

# ==================== ИЗМЕНЕНИЕ КОЛИЧЕСТВА С ПОИСКОМ ====================
@dp.callback_query(F.data == "edit_quantity")
async def edit_quantity_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.edit_quantity_search)
    await callback.message.edit_text(
        "✏️ Изменение количества\n\n"
        "Введите текст для поиска запчасти (можно часть названия или артикула):",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()

@dp.message(Form.edit_quantity_search)
async def edit_quantity_search(message: Message, state: FSMContext):
    query = message.text.strip()
    
    # Ищем по названию или артикулу
    items = await db.fetch("""
        SELECT id, name, article
        FROM items 
        WHERE name ILIKE $1 OR article ILIKE $1
        ORDER BY name
        LIMIT 20
    """, f'%{query}%')
    
    if not items:
        is_admin = await db.is_admin(message.from_user.id)
        await message.answer(
            f"❌ Ничего не найдено по запросу: {query}",
            reply_markup=get_main_keyboard(is_admin)
        )
        await state.clear()
        return
    
    # Показываем результаты поиска
    await message.answer(
        "🔍 Результаты поиска:\n\nВыберите запчасть:",
        reply_markup=get_search_results_keyboard(items, "edit_quantity_select")
    )
    await state.update_data(items=items)
    await state.set_state(Form.edit_quantity_select)

@dp.callback_query(Form.edit_quantity_select, F.data.startswith("edit_quantity_select_"))
async def edit_quantity_select(callback: CallbackQuery, state: FSMContext):
    item_id = int(callback.data.split('_')[3])
    
    item = await db.fetchrow("SELECT id, name, article FROM items WHERE id = $1", item_id)
    if not item:
        is_admin = await db.is_admin(callback.from_user.id)
        await callback.message.edit_text(
            "❌ Запчасть не найдена",
            reply_markup=get_main_keyboard(is_admin)
        )
        await state.clear()
        await callback.answer()
        return
    
    await state.update_data(item_id=item['id'], item_name=item['name'], article=item['article'])
    await state.set_state(Form.edit_quantity_warehouse)
    
    await callback.message.edit_text(
        f"📦 Запчасть: {item['name']}\n🏷 Арт: {item['article']}\n\n"
        f"Выберите склад:",
        reply_markup=await get_warehouses_keyboard("edit_qty")
    )
    await callback.answer()

@dp.callback_query(Form.edit_quantity_warehouse, F.data.startswith("edit_qty_"))
async def edit_quantity_warehouse(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split('_')
    wh_id = int(parts[2])
    wh_name = parts[3]
    
    await state.update_data(wh_id=wh_id, wh_name=wh_name)
    await state.set_state(Form.edit_quantity_new)
    
    # Показываем текущее количество
    data = await state.get_data()
    stock = await db.fetchrow(
        "SELECT quantity FROM stock WHERE item_id = $1 AND warehouse_id = $2",
        data['item_id'], wh_id
    )
    current_qty = stock['quantity'] if stock else 0
    
    await callback.message.edit_text(
        f"🏭 Склад: {wh_name}\n"
        f"📊 Текущее количество: {current_qty} шт.\n\n"
        f"✏️ Введите новое количество:",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()

@dp.message(Form.edit_quantity_new)
async def edit_quantity_new(message: Message, state: FSMContext):
    try:
        new_quantity = int(message.text)
        if new_quantity < 0:
            raise ValueError
        
        data = await state.get_data()
        
        # Обновляем количество
        await db.execute(
            """
            INSERT INTO stock (item_id, warehouse_id, quantity) 
            VALUES ($1, $2, $3)
            ON CONFLICT (item_id, warehouse_id) 
            DO UPDATE SET quantity = $3
            """,
            data['item_id'], data['wh_id'], new_quantity
        )
        
        is_admin = await db.is_admin(message.from_user.id)
        await message.answer(
            f"✅ Количество обновлено!\n\n"
            f"📦 Запчасть: {data['item_name']}\n"
            f"🏷 Артикул: {data['article']}\n"
            f"🏭 Склад: {data['wh_name']}\n"
            f"📊 Новое количество: {new_quantity} шт.",
            reply_markup=get_main_keyboard(is_admin)
        )
        await state.clear()
        
    except:
        await message.answer(
            "❌ Введите корректное число (больше или равно 0)",
            reply_markup=get_cancel_keyboard()
        )

# ==================== ПЕРЕМЕЩЕНИЕ С ПОИСКОМ ====================
@dp.callback_query(F.data == "move")
async def move_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.move_search)
    await callback.message.edit_text(
        "🔄 Перемещение запчасти\n\n"
        "Введите текст для поиска запчасти (можно часть названия или артикула):",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()

@dp.message(Form.move_search)
async def move_search(message: Message, state: FSMContext):
    query = message.text.strip()
    
    # Ищем по названию или артикулу
    items = await db.fetch("""
        SELECT id, name, article
        FROM items 
        WHERE name ILIKE $1 OR article ILIKE $1
        ORDER BY name
        LIMIT 20
    """, f'%{query}%')
    
    if not items:
        is_admin = await db.is_admin(message.from_user.id)
        await message.answer(
            f"❌ Ничего не найдено по запросу: {query}",
            reply_markup=get_main_keyboard(is_admin)
        )
        await state.clear()
        return
    
    # Показываем результаты поиска
    await message.answer(
        "🔍 Результаты поиска:\n\nВыберите запчасть для перемещения:",
        reply_markup=get_search_results_keyboard(items, "move_select")
    )
    await state.update_data(items=items)
    await state.set_state(Form.move_select)

@dp.callback_query(Form.move_select, F.data.startswith("move_select_"))
async def move_select(callback: CallbackQuery, state: FSMContext):
    item_id = int(callback.data.split('_')[2])
    
    item = await db.fetchrow("SELECT id, name, article FROM items WHERE id = $1", item_id)
    if not item:
        is_admin = await db.is_admin(callback.from_user.id)
        await callback.message.edit_text(
            "❌ Запчасть не найдена",
            reply_markup=get_main_keyboard(is_admin)
        )
        await state.clear()
        await callback.answer()
        return
    
    # Показываем текущие остатки
    stocks = await db.fetch("""
        SELECT w.name, s.quantity
        FROM stock s
        JOIN warehouses w ON s.warehouse_id = w.id
        WHERE s.item_id = $1 AND s.quantity > 0
        ORDER BY w.name
    """, item['id'])
    
    stock_text = f"\n📊 Текущие остатки:\n"
    if stocks:
        for s in stocks:
            stock_text += f"   • Склад {s['name']}: {s['quantity']} шт.\n"
    else:
        stock_text += "   ❌ Нет в наличии\n"
    
    await state.update_data(item_id=item['id'], item_name=item['name'], article=item['article'])
    await state.set_state(Form.move_quantity)
    
    await callback.message.edit_text(
        f"📦 Запчасть: {item['name']}\n"
        f"🏷 Артикул: {item['article']}\n"
        f"{stock_text}\n"
        f"🔢 Введите количество для перемещения:",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()

@dp.message(Form.move_quantity)
async def move_quantity(message: Message, state: FSMContext):
    try:
        quantity = int(message.text)
        if quantity <= 0:
            raise ValueError
    except:
        await message.answer(
            "❌ Введите положительное число",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await state.update_data(quantity=quantity)
    await state.set_state(Form.move_from)
    
    await message.answer(
        "🏭 Выберите склад ОТКУДА перемещаем:",
        reply_markup=await get_warehouses_keyboard("from")
    )

@dp.callback_query(Form.move_from, F.data.startswith("from_"))
async def move_from(callback: CallbackQuery, state: FSMContext):
    try:
        parts = callback.data.split('_')
        wh_id = int(parts[1])
        wh_name = parts[2]
        
        await state.update_data(from_wh_id=wh_id, from_wh_name=wh_name)
        await state.set_state(Form.move_to)
        
        await callback.message.edit_text(
            "🏭 Выберите склад КУДА перемещаем:",
            reply_markup=await get_warehouses_keyboard("to")
        )
        await callback.answer()
        
    except Exception as e:
        is_admin = await db.is_admin(callback.from_user.id)
        await callback.message.edit_text(
            f"❌ Ошибка: {e}",
            reply_markup=get_main_keyboard(is_admin)
        )
        await callback.answer()

@dp.callback_query(Form.move_to, F.data.startswith("to_"))
async def move_to(callback: CallbackQuery, state: FSMContext):
    try:
        parts = callback.data.split('_')
        to_wh_id = int(parts[1])
        to_wh_name = parts[2]
        
        data = await state.get_data()
        
        if data.get('from_wh_id') == to_wh_id:
            await callback.message.edit_text(
                "❌ Склады должны быть разными!\n\n"
                "Выберите другой склад:",
                reply_markup=await get_warehouses_keyboard("to")
            )
            await callback.answer()
            return
        
        try:
            async with db.pool.acquire() as conn:
                async with conn.transaction():
                    stock = await conn.fetchrow(
                        "SELECT quantity FROM stock WHERE item_id = $1 AND warehouse_id = $2",
                        data['item_id'], data['from_wh_id']
                    )
                    
                    if not stock or stock['quantity'] < data['quantity']:
                        available = stock['quantity'] if stock else 0
                        await callback.message.edit_text(
                            f"❌ Недостаточно товара!\n\n"
                            f"📦 Запчасть: {data.get('item_name', 'Неизвестно')}\n"
                            f"🏭 Склад: {data.get('from_wh_name', 'Неизвестно')}\n"
                            f"📊 Доступно: {available} шт.\n"
                            f"🔢 Запрошено: {data['quantity']} шт.",
                            reply_markup=get_main_keyboard(await db.is_admin(callback.from_user.id))
                        )
                        await state.clear()
                        await callback.answer()
                        return
                    
                    await conn.execute(
                        "UPDATE stock SET quantity = quantity - $1 WHERE item_id = $2 AND warehouse_id = $3",
                        data['quantity'], data['item_id'], data['from_wh_id']
                    )
                    
                    await conn.execute(
                        """
                        INSERT INTO stock (item_id, warehouse_id, quantity) 
                        VALUES ($1, $2, $3)
                        ON CONFLICT (item_id, warehouse_id) 
                        DO UPDATE SET quantity = stock.quantity + $3
                        """,
                        data['item_id'], to_wh_id, data['quantity']
                    )
                    
                    await conn.execute(
                        """
                        INSERT INTO movements (item_id, from_warehouse_id, to_warehouse_id, quantity, user_id) 
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        data['item_id'], data['from_wh_id'], to_wh_id, data['quantity'], callback.from_user.id
                    )
            
            result_text = (
                f"✅ Перемещение выполнено!\n\n"
                f"📦 Запчасть: {data.get('item_name', 'Неизвестно')}\n"
                f"🏷 Артикул: {data.get('article', 'Неизвестно')}\n"
                f"📊 Количество: {data['quantity']} шт.\n"
                f"⬇️ Со склада: {data.get('from_wh_name', 'Неизвестно')}\n"
                f"⬆️ На склад: {to_wh_name}"
            )
            
            is_admin = await db.is_admin(callback.from_user.id)
            await callback.message.edit_text(
                result_text,
                reply_markup=get_main_keyboard(is_admin)
            )
            await state.clear()
            await callback.answer()
            
        except Exception as e:
            is_admin = await db.is_admin(callback.from_user.id)
            await callback.message.edit_text(
                f"❌ Ошибка при перемещении: {e}",
                reply_markup=get_main_keyboard(is_admin)
            )
            await state.clear()
            await callback.answer()
        
    except Exception as e:
        is_admin = await db.is_admin(callback.from_user.id)
        await callback.message.edit_text(
            f"❌ Ошибка: {e}",
            reply_markup=get_main_keyboard(is_admin)
        )
        await state.clear()
        await callback.answer()

# ==================== ДОБАВЛЕНИЕ ЗАПЧАСТИ ====================
@dp.callback_query(F.data == "add")
async def add_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.add_name)
    await callback.message.edit_text(
        "📦 Введите название запчасти:",
        reply_markup=get_cancel_keyboard()
    )
    await callback.answer()

@dp.message(Form.add_name)
async def add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(Form.add_article)
    await message.answer(
        "🏷 Введите артикул запчасти:",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(Form.add_article)
async def add_article(message: Message, state: FSMContext):
    await state.update_data(article=message.text)
    await state.set_state(Form.add_description)
    await message.answer(
        "📝 Введите описание запчасти (или отправьте '-' если без описания):",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(Form.add_description)
async def add_description(message: Message, state: FSMContext):
    description = message.text if message.text != '-' else ''
    await state.update_data(description=description)
    await state.set_state(Form.add_quantity)
    await message.answer(
        "🔢 Введите начальное количество:",
        reply_markup=get_cancel_keyboard()
    )

@dp.message(Form.add_quantity)
async def add_quantity(message: Message, state: FSMContext):
    try:
        quantity = int(message.text)
        if quantity < 0:
            raise ValueError
        await state.update_data(quantity=quantity)
        await state.set_state(Form.add_warehouse)
        await message.answer(
            "🏭 Выберите склад для размещения:",
            reply_markup=await get_warehouses_keyboard("add")
        )
    except:
        await message.answer(
            "❌ Введите корректное число (больше или равно 0)",
            reply_markup=get_cancel_keyboard()
        )

@dp.callback_query(Form.add_warehouse, F.data.startswith("add_"))
async def add_warehouse(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split('_')
    wh_id = int(parts[1])
    wh_name = parts[2]
    
    data = await state.get_data()
    
    try:
        existing = await db.fetchrow("SELECT id FROM items WHERE article = $1", data['article'])
        if existing:
            is_admin = await db.is_admin(callback.from_user.id)
            await callback.message.edit_text(
                "❌ Ошибка: Артикул уже существует!",
                reply_markup=get_main_keyboard(is_admin)
            )
            await state.clear()
            await callback.answer()
            return
        
        query = "INSERT INTO items (name, article, description) VALUES ($1, $2, $3) RETURNING id"
        result = await db.fetchrow(query, data['name'], data['article'], data['description'])
        item_id = result['id']
        
        if data['quantity'] > 0:
            await db.execute(
                "INSERT INTO stock (item_id, warehouse_id, quantity) VALUES ($1, $2, $3)",
                item_id, wh_id, data['quantity']
            )
        
        result_text = f"✅ Запчасть успешно добавлена!\n\n"
        result_text += f"📦 Название: {data['name']}\n"
        result_text += f"🏷 Артикул: {data['article']}\n"
        if data['description']:
            result_text += f"📝 Описание: {data['description']}\n"
        result_text += f"📊 Количество: {data['quantity']} шт.\n"
        result_text += f"🏭 Склад: {wh_name}\n"
        result_text += f"🆔 ID: {item_id}"
        
        is_admin = await db.is_admin(callback.from_user.id)
        await callback.message.edit_text(
            result_text,
            reply_markup=get_main_keyboard(is_admin)
        )
        await state.clear()
        await callback.answer()
        
    except Exception as e:
        is_admin = await db.is_admin(callback.from_user.id)
        await callback.message.edit_text(
            f"❌ Ошибка: {e}",
            reply_markup=get_main_keyboard(is_admin)
        )
        await state.clear()
        await callback.answer()

@dp.message(Form.add_warehouse)
async def add_warehouse_text(message: Message, state: FSMContext):
    """Если пользователь ввел текст вместо нажатия кнопки"""
    await message.answer(
        "❌ Пожалуйста, выберите склад из списка кнопок ниже:",
        reply_markup=await get_warehouses_keyboard("add")
    )

# ==================== УДАЛЕНИЕ СТАРЫХ СООБЩЕНИЙ ====================
@dp.callback_query(F.data == "delete_old")
async def delete_old_callback(callback: CallbackQuery):
    await callback.answer("🧹 Очистка чата...")
    
    try:
        is_admin = await db.is_admin(callback.from_user.id)
        await callback.message.edit_text(
            f"✅ Чат очищен!\n\n"
            f"Текущее меню сохранено.",
            reply_markup=get_main_keyboard(is_admin)
        )
        
    except Exception as e:
        is_admin = await db.is_admin(callback.from_user.id)
        await callback.message.edit_text(
            f"❌ Ошибка при удалении: {e}",
            reply_markup=get_main_keyboard(is_admin)
        )

async def main():
    success = await db.create_pool()
    if not success:
        print("❌ Не удалось подключиться к БД. Завершаем работу.")
        return
    
    print("🤖 Бот запущен...")
    print(f"👑 Главный администратор ID: {ADMIN_IDS}")
    try:
        await dp.start_polling(bot)
    finally:
        await db.close()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен")