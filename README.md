# Ellie — Discord channel mute bot

Модераторский бот для **временного запрета отправки сообщений** в конкретном текстовом канале (один сервер). Спецификация: [TODO_0_1.md](TODO_0_1.md).

## Требования

- Python 3.12+
- Discord bot token
- Права бота на сервере: **Управление каналами** (`Manage Channels`), роль бота **выше** наказываемых пользователей

## Установка

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

Скопируйте примеры конфигурации:

```bash
copy config\config.yaml.example config\config.yaml
copy config\roles.yaml.example config\roles.yaml
copy .env.example .env
```

Заполните:

| Файл | Поля |
|------|------|
| `.env` | `DISCORD_TOKEN` |
| `config/config.yaml` | `guild_id`, `moderator_commands_channel_id`, `bot_logs_channel_id`, `database_path`, `log_level` |
| `config/roles.yaml` | `role_ids` — ID ролей модераторов **сверху вниз** (старшие → младшие); старшая роль может наказывать младшую |

## Запуск

```bash
python bot.py
```

Slash-команды синхронизируются **только с guild** из `guild_id` (мгновенно после запуска).

## Команды

| Команда | Где вызывать |
|---------|----------------|
| `/mute_user` | Текстовый канал наказания или бот-команды + `channel` |
| `/unmute_user` | Текстовый канал или бот-команды + `channel` |
| `/active_mutes` | Только бот-команды (`user` или `user_id`) |
| `/mute_help` | Только бот-команды |

В публичных каналах ответы бота **ephemeral** (видит только модератор). Действия пишутся в канал **логов ботов**.

## Структура проекта

```
bot.py                 # Точка входа
core/                  # Конфиг, права, ответы, контекст каналов
database/              # SQLite, модели, миграции
modules/channel_mutes/ # Mute, scheduler, команды, audit
config/                # config.yaml, roles.yaml
logs/                  # Файловые логи (создаётся автоматически)
```

### Добавление нового модуля

1. Создайте пакет в `modules/<name>/` (commands, service, repository).
2. Зарегистрируйте cog в `bot.py` → `setup_hook`.
3. Добавьте миграции в `database/migrations.py` при необходимости.
4. Опишите команды в README.

## Чеклист ручного тестирования

- [ ] `/mute_user` в публичном канале — ephemeral ответ, запись в лог-канале, DM пользователю
- [ ] `/mute_user` из бот-команд с `channel`
- [ ] Повторный mute — «продлил» в логах, новый срок
- [ ] `/unmute_user` в канале и из бот-команд
- [ ] Авто-снятие (mute на `1m`), запись в лог-канале от имени бота
- [ ] `/active_mutes` с `user` и с `user_id`
- [ ] `/mute_help` в бот-командах
- [ ] Ошибки: нет прав, неверный `duration`, пользователь не наказан, команда в лог-канале
- [ ] Перезапуск бота — активные mutes перепланируются

## Логи

- Консоль и `logs/bot.log` (ротация)
- Модераторские действия — канал `bot_logs_channel_id`
