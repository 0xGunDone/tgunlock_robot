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
1. `free_credit = 50` — стартовый баланс для бесплатного прокси.
2. `max_active_proxies = 10` — лимит активных прокси на пользователя (0 = без лимита).
3. `proxy_create_price = 100` — разовая цена создания прокси.
4. `proxy_day_price = 10` — цена за 1 день активного прокси.
5. `ref_bonus_invited = 10` — бонус приглашённому.
6. `ref_bonus_inviter = 10` — бонус пригласившему.
7. `referral_enabled = 1` — включение рефералки (0 = выкл).
8. `stars_rate = 1` — курс Stars к рублю (1 Star = 1 ₽).
9. `stars_buy_url = ""` — ссылка где купить Stars (если нужна подсказка).
10. `stars_buy_hint_enabled = 0` — показывать подсказку где купить Stars (0/1).
11. `socks_enabled = 1` — показывать SOCKS ссылку (0/1).
12. `mtproto_enabled = 0` — показывать MTProto ссылку (0/1).
13. `mtproto_host = ""` — хост MTProto (если пусто, используется `PROXY_DEFAULT_IP`).
14. `mtproto_port = 9443` — порт MTProto.

`mtproto_secret` больше не настраивается вручную — секрет создаётся автоматически для каждого прокси.

## MTProto (персональные секреты)

Для контроля доступа у каждого прокси свой secret. Бот хранит их в файле и перезапускает MTProxy,
когда список секретов меняется (создание/удаление/блокировка прокси).
Для этого сервис бота должен иметь права на `systemctl restart mtproxy.service`.

Опциональные переменные окружения:
- `MTPROXY_SECRETS_FILE` — путь к файлу секретов (по умолчанию `data/mtproxy_secrets.txt`).
- `MTPROXY_SERVICE` — имя systemd‑сервиса MTProxy (по умолчанию `mtproxy.service`).

Пример wrapper‑скрипта (используется в systemd unit):

```bash
#!/usr/bin/env bash
set -euo pipefail
SECRETS_FILE="${MTPROXY_SECRETS_FILE:-/storage/tgunlock_robot/data/mtproxy_secrets.txt}"
PORT="${MTPROXY_PORT:-9443}"
ARGS=()
if [[ -f "$SECRETS_FILE" ]]; then
  while IFS= read -r secret; do
    secret="$(echo -n "$secret" | tr -d '[:space:]')"
    [[ -z "$secret" ]] && continue
    ARGS+=("-S" "$secret")
  done < "$SECRETS_FILE"
fi
exec /opt/MTProxy/objs/bin/mtproto-proxy -u nobody -p 8888 -H "$PORT" "${ARGS[@]}" --aes-pwd /opt/MTProxy/proxy-secret /opt/MTProxy/proxy-multi.conf -M 1
```

Важно: `mtproto_port` в админке и порт в systemd должны совпадать.

Готовые файлы в репозитории:
- `scripts/mtproxy_start.sh`
- `mtproxy.service` (проверьте пути и `MTPROXY_PORT`)

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
