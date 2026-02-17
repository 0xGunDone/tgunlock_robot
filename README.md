# Telegram MTProto Proxy Bot

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
- `PROXY_DEFAULT_IP` (публичный домен/IP; используется как fallback для MTProto host)
- `FREEKASSA_SHOP_ID` (если используете FreeKassa API)
- `FREEKASSA_API_KEY`
- `FREEKASSA_SECRET_WORD_2` (секретное слово №2, для webhook)
- `FREEKASSA_API_BASE` (по умолчанию `https://api.fk.life/v1`)
- `FREEKASSA_IP` (IP клиента; можно указать IP сервера)
- `FREEKASSA_RECONCILE_INTERVAL_SEC` (фоновая сверка pending-платежей, по умолчанию `180`)
- `MTPROXY_RESTART_COOLDOWN_SEC` (защита от частых рестартов MTProxy, по умолчанию `30`)
- `RATE_LIMIT_START_PER_MIN` (лимит `/start` на пользователя в минуту, по умолчанию `10`)
- `RATE_LIMIT_TOPUP_PER_MIN` (лимит действий пополнения, по умолчанию `20`)
- `RATE_LIMIT_SUPPORT_PER_MIN` (лимит сообщений в поддержку, по умолчанию `8`)

3. Запустите сервер:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Webhook будет установлен автоматически на `WEBHOOK_URL`.

Если используете FreeKassa API, укажите URL оповещений:
`https://<ваш-домен>/<APP_PREFIX>/freekassa` (или `/freekassa`, если `APP_PREFIX` пустой).

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
9. `stars_enabled = 1` — включить оплату Stars (0/1).
10. `freekassa_enabled = 0` — включить оплату FreeKassa (0/1).
11. `freekassa_method_44_enabled = 1` — включить СБП QR (id 44).
12. `freekassa_method_36_enabled = 1` — включить карты РФ (id 36).
13. `freekassa_method_43_enabled = 1` — включить SberPay (id 43).
14. `stars_buy_url = ""` — ссылка где купить Stars (если нужна подсказка).
15. `stars_buy_hint_enabled = 0` — показывать подсказку где купить Stars (0/1).
16. `mtproto_enabled = 1` — показывать MTProto ссылку (0/1).
17. `mtproto_host = ""` — хост MTProto (если пусто, используется `PROXY_DEFAULT_IP`).
18. `mtproto_port = 9443` — порт MTProto.
19. `bg_enabled = 1` — включить фоновую картинку в меню (0/1).
20. `offer_enabled = 1` — показывать публичную оферту при `/start` (0/1).
21. `policy_enabled = 1` — показывать политику при `/start` (0/1).
22. `offer_url = ""` — ссылка на оферту.
23. `policy_url = ""` — ссылка на политику.
24. `support_sla_minutes = 30` — через сколько минут без ответа тикет считается просроченным.

`mtproto_secret` больше не настраивается вручную — секрет создаётся автоматически для каждого прокси.

## MTProto (персональные секреты)

Для контроля доступа у каждого прокси свой secret. Бот хранит их в файле и перезапускает MTProxy,
когда список секретов меняется (создание/удаление/блокировка прокси).
Для этого сервис бота должен иметь права на `systemctl restart mtproxy.service`.
Если бот запускается от root — дополнительных прав не нужно.

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
3. Все переключатели делаются кнопками.
4. Для числовых полей нажми кнопку и введи значение.

Примеры:
```
proxy_day_price 10
proxy_create_price 100
free_credit 50
stars_rate 1
ref_bonus_inviter 10
ref_bonus_invited 10
stars_buy_hint_enabled 1
stars_buy_url https://t.me/BuyStarsBot
offer_url https://example.com/offer
policy_url https://example.com/policy
```

## Поддержка и платежи

- Поддержка работает по статусам тикета: `waiting_admin`, `waiting_user`, `closed`.
- Тикет можно закрыть админом или самим пользователем.
- Для FreeKassa добавлена кнопка `Проверить оплату`.
- В фоне работает сверка `pending` платежей, если webhook задержался.
