# Telegram SOCKS5 Proxy Bot

## Запуск

1. Установите зависимости:

```bash
pip install -r requirements.txt
```

2. Задайте переменные окружения:

- `BOT_TOKEN`
- `WEBHOOK_URL`
- `WEBHOOK_SECRET` (опционально)
- `ADMIN_TG_IDS` (например: `123456789,987654321`)
- `DB_PATH` (по умолчанию `data/bot.db`)
- `APP_PREFIX` (если проксируете под путём, например `/tgunlock_robot`)

3. Запустите сервер:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Webhook будет установлен автоматически на `WEBHOOK_URL`.

## Провайдер прокси

По умолчанию используется мок-провайдер. Для интеграции с реальным SOCKS5-сервером:

- `PROXY_PROVIDER=command`
- `PROXY_CMD_CREATE` — команда создания (должна вывести `IP PORT`)
- `PROXY_CMD_UPDATE_PASSWORD` — команда смены пароля
- `PROXY_CMD_DISABLE` — команда отключения

Команды поддерживают плейсхолдеры `{login}` и `{password}`.

### Dante (PAM, username)

Если у вас настроен Dante с `method: username`, бот может сам создавать системных пользователей:

```
PROXY_PROVIDER=danted
PROXY_DEFAULT_IP=ваш_публичный_IP_или_домен
PROXY_DEFAULT_PORT=1080
PROXY_CMD_PREFIX=sudo
```

Требования:
- сервис бота должен иметь права на `useradd`, `chpasswd`, `usermod`.
- либо запустить systemd‑сервис под root,
- либо выдать sudo‑права на эти команды.

## Настройки (БД settings)

Все значения — в рублях, кроме `stars_rate`.

Значения по умолчанию:
1. `device_limit = 0` — лимит устройств (0 = без лимита).
2. `free_credit = 50` — стартовый баланс для бесплатного прокси.
3. `max_active_proxies = 10` — лимит активных прокси на пользователя (0 = без лимита).
4. `proxy_create_price = 100` — разовая цена создания прокси.
5. `proxy_day_price = 10` — цена за 1 день активного прокси.
6. `ref_bonus_invited = 10` — бонус приглашённому.
7. `ref_bonus_inviter = 10` — бонус пригласившему.
8. `referral_enabled = 1` — включение рефералки (0 = выкл).
9. `stars_rate = 1` — курс Stars к рублю (1 Star = 1 ₽).

## Админка: изменение настроек

1. Открой админку командой `/admin`.
2. Нажми `⚙️ Настройки`.
3. Бот покажет список текущих параметров.
4. Отправь строку в формате:
```
ключ значение
```

Примеры:
```
proxy_day_price 10
proxy_create_price 100
free_credit 50
stars_rate 1
ref_bonus_inviter 10
ref_bonus_invited 10
```
