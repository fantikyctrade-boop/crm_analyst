# Overture Lead Telegram Bot

Telegram-бот на `aiogram 3`, який керує наявними модулями
`lead_collector.py` і `lead_scorer.py`. Алгоритми збору й скорингу не
дублюються: сервіс напряму викликає їхні функції.

## Можливості

- FSM-сценарій: ніша → міста → ліміт → підтвердження;
- збір і скоринг у робочому потоці без блокування Telegram polling;
- whitelist за Telegram `user_id`;
- заборона двох одночасних пошуків для одного користувача;
- статистика HIGH / MEDIUM / LOW і пагінація по 10 компаній;
- фільтр HIGH та повторне завантаження `scored_leads.csv`;
- окрема тимчасова директорія для кожного запуску;
- видалення проміжного `leads.csv`, попереднього запуску користувача та
  всіх залишків під час запуску/зупинки бота.

## Встановлення

Потрібен Python 3.12.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Створіть `.env` із прикладу:

```powershell
Copy-Item .env.example .env
```

Заповніть значення:

```dotenv
BOT_TOKEN=токен_від_BotFather
ALLOWED_USER_IDS=123456789,987654321
```

`ALLOWED_USER_IDS` — числові Telegram user ID через кому. Оновлення від
інших користувачів блокуються middleware.

Щоб тимчасово дозволити доступ усім користувачам, встановіть
`ALLOWED_USER_IDS=*`. Для робочого використання поверніть конкретні ID.

## Запуск

```powershell
python bot.py
```

## Перевірки без запуску Telegram

```powershell
python -m py_compile bot.py config.py handlers\*.py services\*.py
ruff check bot.py config.py handlers services tests
python -m unittest discover -s tests -v
```

Mock-тест не звертається до Telegram, Overture або Nominatim. Він перевіряє
повний локальний ланцюжок: параметри → mocked collection → реальний scoring →
`scored_leads.csv` → статистика → очищення попереднього запуску.

## Примітки

- `BOT_TOKEN` читається лише з `.env` і не записується в код.
- Поточний CSV зберігається, доки він потрібен кнопці завантаження. Після
  наступного успішного пошуку попередня директорія користувача видаляється.
- Після перезапуску бота FSM і поточні результати в пам'яті скидаються.
- Бот не використовує AI, LLM, Selenium, Google Maps або CRM.
