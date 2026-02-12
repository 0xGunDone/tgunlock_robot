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
