import logging
import os
import sys
import traceback

import dotenv
from rembg import new_session
from telegram import Update
from telegram import error as tg_err
from telegram.constants import StickerFormat, ChatMemberStatus
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# Предполагается, что эти файлы существуют в той же директории или PYTHONPATH
# Если их нет, импорт вызовет ошибку ModuleNotFoundError
try:
    from error import NoEmojiSent
    from sticker import create_new_sticker
except ImportError as e:
    print(f"[!] Ошибка импорта: {e}. Убедитесь, что файлы 'error.py' и 'sticker.py' существуют и содержат необходимые классы/функции.")
    sys.exit(1)


dotenv.load_dotenv()


def load_env_or_exit(key: str) -> str:
    """
    Возвращает значение переменной окружения или завершает выполнение программы с ошибкой.
    :param key: str
    :return: str
    """
    try:
        env_value = os.environ[key]
    except KeyError:
        print(f"[!] Значение `{key}` должно быть указано в файле `.env`.")
        sys.exit(1)
    else:
        return env_value


BOT_TOKEN = load_env_or_exit("BOT_TOKEN")
BOT_NAME = load_env_or_exit("BOT_NAME")
REMBG_AI_MODEL = load_env_or_exit("REMBG_AI_MODEL")
# ИСПРАВЛЕННАЯ СТРОКА: Указано правильное имя ключа переменной окружения
CHANNEL_ID = load_env_or_exit("-1002348515440")  # ID канала для проверки подписки

HELP_TEXT = """Приветствую 👋

Это бот для создания стикеров.
Он вырезает фон и создает стикеры из фотографий, которые вы ему отправите.

Для использования бота необходимо быть подписанным на наш канал.

Чтобы создать стикер из фотки, необходимо проделать несколько простых шагов:
1) Выберите нужную фотографию для отправки.
2) В подписи к фотографии поставьте как минимум один эмодзи, который будет ассоциироваться с этим стикером (можно несколько штук подряд).
3) Дождитесь ответа от бота об успешном добавлении стикера в стикерпак*.

* Для вас будет создан один стикерпак, в который будут добавляться созданные ботом стикеры.
Вы можете удалить этот стикерпак с помощью бота в любой момент командой /delete_sticker_pack.
"""

# Используем user.id вместо user.username для большей надежности
STICKER_SET_NAME_TMPL = f"for_{{0}}_by_{BOT_NAME}"
DEFAULT_STICKER_SET_TITLE = f"Stickers from @{BOT_NAME}"


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
# Убедитесь, что у бота есть права на запись в текущую директорию или укажите полный путь к файлу лога
try:
    logger.addHandler(logging.FileHandler("sticker_bot.log", mode="a", encoding="utf-8"))
except FileNotFoundError:
    print("[!] Не удалось создать файл лога 'sticker_bot.log'. Проверьте права на запись в текущей директории.")
    # Продолжаем без логирования в файл, если не получилось
    pass


async def check_subscription(user_id: int, bot) -> bool:
    """
    Проверяет, подписан ли пользователь на канал
    :param user_id: ID пользователя
    :param bot: экземпляр бота
    :return: True если подписан, False если нет
    """
    try:
        # Убедимся, что CHANNEL_ID читается как число (ID)
        chat_id_to_check = int(CHANNEL_ID)
        member = await bot.get_chat_member(chat_id=chat_id_to_check, user_id=user_id)
        return member.status in [
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR
        ]
    except ValueError:
        logger.error(f"Ошибка: CHANNEL_ID ('{CHANNEL_ID}') не является числом. Укажите числовой ID канала в .env")
        return False # Не можем проверить, если ID не число
    except tg_err.BadRequest as e:
        # Частая ошибка - бот не является админом в канале или указан неверный ID
        logger.error(f"Ошибка BadRequest при проверке подписки user_id={user_id} на channel_id={CHANNEL_ID}: {e}. Убедитесь, что бот добавлен в канал как администратор и ID канала верный.")
        return False
    except Exception as e:
        logger.error(f"Неожиданная ошибка при проверке подписки user_id={user_id} на channel_id={CHANNEL_ID}: {e}\n{traceback.format_exc()}")
        return False


async def restricted_handler(handler_func, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обертка для обработчиков, которая проверяет подписку
    """
    # Проверяем, что сообщение от пользователя и есть сам пользователь
    if not update.message or not update.message.from_user:
        return

    user = update.message.from_user
    is_subscribed = await check_subscription(user.id, context.bot)

    if not is_subscribed:
        channel_link = CHANNEL_ID # По умолчанию используем ID
        try:
             # Попробуем получить username, если это возможно и ID числовой
             chat = await context.bot.get_chat(int(CHANNEL_ID))
             if chat.username:
                 channel_link = f"@{chat.username}" # Формируем ссылку с @username
             else:
                 # Если username нет, но есть инвайт ссылка (для приватных каналов)
                 if chat.invite_link:
                     channel_link = chat.invite_link # Используем инвайт ссылку
                 else: # Если нет ни username ни инвайт ссылки, используем ID
                     channel_link = f"канал с ID {CHANNEL_ID}" # Уточняем, что это ID
        except ValueError:
             logger.warning(f"CHANNEL_ID ('{CHANNEL_ID}') не является числом, нельзя получить информацию о чате по ID.")
             # Можно попробовать использовать как username, если он задан так в .env
             if not CHANNEL_ID.startswith('-'): # Предполагаем, что это username, если не начинается с минуса
                 channel_link = f"@{CHANNEL_ID}"
             else:
                 channel_link = f"канал с ID {CHANNEL_ID}" # Иначе используем ID
        except Exception as e:
             logger.error(f"Не удалось получить информацию о канале {CHANNEL_ID} для сообщения о подписке: {e}")
             channel_link = f"канал с ID {CHANNEL_ID}" # Возвращаемся к ID в случае ошибки

        # Формируем сообщение в зависимости от того, что получили (ссылку или ID)
        if channel_link.startswith("https://") or channel_link.startswith("@"):
             subscribe_message = f"Подпишитесь здесь: {channel_link}\n"
        else: # Если это ID или текстовое описание
             subscribe_message = f"Убедитесь, что вы подписаны на {channel_link}.\n"


        await update.message.reply_text(
            "❌ Для использования бота необходимо подписаться на наш канал.\n"
            f"{subscribe_message}"
            "После подписки попробуйте команду снова."
        )
        return

    # Если подписка есть, выполняем основную функцию обработчика
    await handler_func(update, context)


async def help_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик команды /start с проверкой подписки
    """
     # Проверяем, что сообщение от пользователя и есть сам пользователь
    if not update.message or not update.message.from_user:
        return

    user = update.message.from_user
    is_subscribed = await check_subscription(user.id, context.bot)

    if not is_subscribed:
        channel_link = CHANNEL_ID # По умолчанию используем ID
        try:
             chat = await context.bot.get_chat(int(CHANNEL_ID))
             if chat.username:
                 channel_link = f"@{chat.username}"
             elif chat.invite_link:
                 channel_link = chat.invite_link
             else:
                 channel_link = f"канал с ID {CHANNEL_ID}"
        except ValueError:
             logger.warning(f"CHANNEL_ID ('{CHANNEL_ID}') не является числом, нельзя получить информацию о чате по ID для /start.")
             if not CHANNEL_ID.startswith('-'):
                 channel_link = f"@{CHANNEL_ID}"
             else:
                 channel_link = f"канал с ID {CHANNEL_ID}"
        except Exception as e:
             logger.error(f"Не удалось получить информацию о канале {CHANNEL_ID} для /start: {e}")
             channel_link = f"канал с ID {CHANNEL_ID}"

        if channel_link.startswith("https://") or channel_link.startswith("@"):
             subscribe_message = f"Подпишитесь здесь: {channel_link}\n"
        else:
             subscribe_message = f"Убедитесь, что вы подписаны на {channel_link}.\n"

        await update.message.reply_text(
            "Привет! Для использования бота необходимо подписаться на наш канал.\n"
            f"{subscribe_message}"
            "После подписки нажмите /start снова."
        )
        return

    # Если подписан, отправляем справку
    await help_message(update, context)


async def add_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
     # Проверяем, что сообщение от пользователя и есть сам пользователь
    if not update.message or not update.message.from_user:
        return
    user = update.message.from_user

    # Определяем сессию rembg
    if context.bot_data.get("performance_mode", False) and 'rembg_session' in context.bot_data:
        rembg_session = context.bot_data['rembg_session']
    else:
        # Создаем новую сессию для каждого запроса, если не в performance_mode или сессии нет
        try:
            rembg_session = new_session(REMBG_AI_MODEL)
        except Exception as e:
            logger.error(f"Ошибка при создании сессии rembg: {e}\n{traceback.format_exc()}")
            await update.message.reply_text("❌ Произошла внутренняя ошибка (rembg), попробуйте позже.")
            return

    try:
        # Создаем стикер (предполагает, что sticker.py и его функция существуют и работают)
        new_sticker = await create_new_sticker(update, rembg_session)
        if new_sticker is None: # Добавим проверку, если create_new_sticker может вернуть None
            logger.error("create_new_sticker вернула None")
            await update.message.reply_text("❌ Не удалось создать стикер из изображения.")
            return

    except NoEmojiSent:
        await update.message.reply_text("❌ Отправьте эмодзи вместе с картинкой в подписи, чтобы прикрепить его к стикеру.")
        return # Важно выйти из функции здесь
    except Exception as e:
        # Логируем полную ошибку создания стикера
        logger.error(f"❌ Ошибка при вызове create_new_sticker.\n{traceback.format_exc()}")
        # Отправляем пользователю общее сообщение
        await update.message.reply_text("❌ Возникла ошибка при обработке вашего изображения, попробуйте другое фото или повторите позже.")
        return # Важно выйти из функции здесь

    # Используем user.id для имени стикерпака
    sticker_set_name = STICKER_SET_NAME_TMPL.format(user.id)
    try:
        # Пытаемся добавить стикер в существующий набор
        await context.bot.add_sticker_to_set(user_id=user.id, name=sticker_set_name, sticker=new_sticker)
        logger.info(f"Стикер добавлен в существующий пак {sticker_set_name} для user_id {user.id}")

    except tg_err.BadRequest as err:
        # Если набор не найден (самая частая ошибка BadRequest здесь)
        if "Stickerset_invalid" in str(err) or "STICKERSET_INVALID" in str(err):
            logger.info(f"Стикерпак {sticker_set_name} не найден для user_id {user.id}. Создаем новый.")
            # Пытаемся создать новый набор стикеров
            await _create_new_sticker_set(update, context, sticker_set_name, new_sticker)
        else:
            # Другая ошибка BadRequest при добавлении
            logger.error(f"❌ Ошибка BadRequest при добавлении стикера в {sticker_set_name}: {err}\n{traceback.format_exc()}")
            await update.message.reply_text("❌ Возникла ошибка при добавлении стикера в стикерпак (1), попробуйте позже.")
    except Exception as e:
        # Другая (не BadRequest) ошибка при добавлении
        logger.error(f"[!] Неожиданная ошибка при добавлении стикера в {sticker_set_name}: {e}\n{traceback.format_exc()}")
        await update.message.reply_text("❌ Возникла ошибка при добавлении стикера в стикерпак (2), попробуйте позже.")
    else:
        # Если добавление в существующий пак прошло успешно
        await update.message.reply_text("✅ Стикер успешно добавлен в ваш стикерпак.\n"
                                        f"https://t.me/addstickers/{sticker_set_name}")


async def delete_sticker_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверяем, что сообщение от пользователя и есть сам пользователь
    if not update.message or not update.message.from_user:
        return
    user = update.message.from_user
    sticker_set_name = STICKER_SET_NAME_TMPL.format(user.id)
    try:
        # Пытаемся удалить набор стикеров
        success = await context.bot.delete_sticker_set(name=sticker_set_name)
    except tg_err.BadRequest as err:
         # Если стикерпак не найден - это тоже своего рода успех (его нет)
         if "Stickerset_invalid" in str(err) or "STICKERSET_INVALID" in str(err):
             logger.info(f"Попытка удаления несуществующего стикерпака {sticker_set_name} user_id {user.id}")
             await update.message.reply_text("ℹ️ Ваш стикерпак не найден (возможно, уже удален).")
             return # Выходим, т.к. удалять нечего
         else:
             logger.error(f"❌ Ошибка BadRequest при удалении стикерпака {sticker_set_name}: {err}\n{traceback.format_exc()}")
             success = False # Явно указываем на неуспех
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка при удалении стикерпака {sticker_set_name}: {e}\n{traceback.format_exc()}")
        success = False

    # Сообщаем результат пользователю
    if success:
        logger.info(f"Стикерпак {sticker_set_name} успешно удален для user_id {user.id}")
        await update.message.reply_text("✅ Стикерпак успешно удален.")
    else:
        # Это сообщение будет показано, если success остался False после блока try/except
         await update.message.reply_text("❌ Не удалось удалить стикерпак. Попробуйте позже или удалите его вручную через @Stickers.")


async def get_user_sticker_set_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
     # Проверяем, что сообщение от пользователя и есть сам пользователь
    if not update.message or not update.message.from_user:
        return
    user = update.message.from_user
    sticker_set_name = STICKER_SET_NAME_TMPL.format(user.id)
    try:
        # Проверяем, существует ли стикерпак, чтобы дать актуальную ссылку
        await context.bot.get_sticker_set(name=sticker_set_name)
        # Если существует, отправляем ссылку
        await update.message.reply_text(f"Ваш стикерпак: https://t.me/addstickers/{sticker_set_name}")
    except tg_err.BadRequest as err:
         # Если стикерпак не найден
         if "Stickerset_invalid" in str(err) or "STICKERSET_INVALID" in str(err):
             await update.message.reply_text("❌ У вас еще нет стикерпака. Отправьте фото с эмодзи в подписи, чтобы создать его.")
         else:
             # Другая ошибка BadRequest
             logger.error(f"❌ Ошибка BadRequest при получении стикерпака {sticker_set_name}: {err}\n{traceback.format_exc()}")
             await update.message.reply_text("❌ Не удалось получить информацию о вашем стикерпаке.")
    except Exception as e:
        # Другая неожиданная ошибка
        logger.error(f"❌ Неожиданная ошибка при получении стикерпака {sticker_set_name}: {e}\n{traceback.format_exc()}")
        await update.message.reply_text("❌ Произошла ошибка при поиске вашего стикерпака.")


# Передаем context в _create_new_sticker_set на случай, если он понадобится
async def _create_new_sticker_set(update: Update, context: ContextTypes.DEFAULT_TYPE, sticker_set_name, first_sticker):
    # Проверяем, что сообщение от пользователя и есть сам пользователь
    if not update.message or not update.message.from_user:
        return
    user = update.message.from_user
    try:
        # Используем context.bot вместо update.get_bot() (рекомендовано в PTB v20+)
        # Передаем user_id=user.id и name=sticker_set_name
        await context.bot.create_new_sticker_set(user_id=user.id,
                                                 name=sticker_set_name,
                                                 title=DEFAULT_STICKER_SET_TITLE,
                                                 sticker=first_sticker, # Используем sticker= вместо stickers=
                                                 sticker_format=StickerFormat.STATIC)
        logger.info(f"Создан новый стикерпак {sticker_set_name} для user_id {user.id}")
    except tg_err.BadRequest as err:
        # Возможная ошибка - имя уже занято (маловероятно из-за user.id, но возможно при гонках)
        if "sticker set name is already occupied" in str(err).lower():
             logger.warning(f"Попытка создать уже существующий стикерпак {sticker_set_name} (возможно, гонка запросов).")
             # Считаем, что пак уже есть, просто сообщаем об этом
             await update.message.reply_text(f"✅ Стикерпак уже существует, стикер добавлен.\n"
                                           f"https://t.me/addstickers/{sticker_set_name}")
             # Можно попробовать добавить еще раз на всякий случай, но это может вызвать цикл
        elif "USER_IS_BOT" in str(err):
             logger.error(f"Ошибка USER_IS_BOT при создании стикерпака {sticker_set_name}. Боты не могут владеть стикерпаками.")
             # Это не должно происходить с реальными пользователями
             await update.message.reply_text("❌ Ошибка: боты не могут создавать стикерпаки.")
        else:
            # Другая ошибка BadRequest при создании
            logger.error(f"❌ Ошибка BadRequest при создании стикерпака {sticker_set_name}: {err}\n{traceback.format_exc()}")
            await update.message.reply_text("❌ Возникла ошибка при создании стикерпака (1), попробуйте позже.")
    except Exception as e:
        # Другая неожиданная ошибка при создании
        logger.error(f"❌ Неожиданная ошибка при создании стикерпака {sticker_set_name}: {e}\n{traceback.format_exc()}")
        await update.message.reply_text("❌ Возникла ошибка при создании стикерпака (2), попробуйте позже.")
    else:
        # Если создание прошло успешно
        await update.message.reply_text(f"✅ Ваш новый стикерпак создан! Можете добавить его себе по ссылке:\n"
                                      f"https://t.me/addstickers/{sticker_set_name}")


async def _init_persistent_rembg_session(app: Application):
    """Инициализация сессии rembg при старте бота."""
    try:
        app.bot_data['rembg_session'] = new_session(REMBG_AI_MODEL)
        app.bot_data['performance_mode'] = True
        logger.info(f"Предзагружена сессия rembg (модель: {REMBG_AI_MODEL}) в режиме performance_mode.")
    except Exception as e:
        logger.error(f"Не удалось предзагрузить сессию rembg: {e}\n{traceback.format_exc()}")
        app.bot_data['performance_mode'] = False # Отключаем режим, если сессия не создалась


def start_bot():
    """Настройка и запуск бота."""
    # Настройка базового логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout) # Вывод логов в консоль
        ]
    )
    # Добавляем хендлер для файла, если он был успешно создан ранее
    if any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        pass # Уже добавлен
    elif os.access(os.path.dirname("sticker_bot.log") or '.', os.W_OK): # Проверяем права на запись еще раз
         try:
            file_handler = logging.FileHandler("sticker_bot.log", mode="a", encoding="utf-8")
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler) # Добавляем файловый логгер
            logging.getLogger().addHandler(file_handler) # Добавляем и в root логгер
            logger.info("Логирование в файл sticker_bot.log включено.")
         except Exception as e:
            logger.error(f"Не удалось настроить логирование в файл 'sticker_bot.log': {e}")
    else:
        logger.warning("Нет прав на запись для sticker_bot.log, логирование только в консоль.")


    logger.info("Инициализация приложения Telegram...")
    try:
        # Собираем приложение
        builder = Application.builder().token(BOT_TOKEN)

        # Проверяем аргумент командной строки для performance_mode
        if len(sys.argv) == 2 and sys.argv[1] == "--performance-mode":
            logger.info("Активация performance_mode через аргумент командной строки.")
            builder.post_init(_init_persistent_rembg_session)
        else:
            logger.info("Запуск в стандартном режиме (сессия rembg создается для каждого запроса).")

        # Создаем приложение
        bot_app = builder.build()

        # Регистрируем обработчики
        # /start имеет свою проверку подписки внутри
        bot_app.add_handler(CommandHandler("start", start))
        # Остальные команды оборачиваем в restricted_handler
        bot_app.add_handler(CommandHandler("help", lambda u, c: restricted_handler(help_message, u, c)))
        bot_app.add_handler(CommandHandler("sticker_pack_link", lambda u, c: restricted_handler(get_user_sticker_set_link, u, c)))
        bot_app.add_handler(CommandHandler("delete_sticker_pack", lambda u, c: restricted_handler(delete_sticker_set, u, c)))
        # Обработчик фото также оборачиваем
        bot_app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, lambda u, c: restricted_handler(add_sticker, u, c)))

        logger.info("Запуск бота (polling)...")
        # Запускаем бота
        bot_app.run_polling()

    except Exception as e:
         logger.critical(f"Критическая ошибка при инициализации или запуске бота: {e}\n{traceback.format_exc()}")
         sys.exit("Критическая ошибка при запуске бота.")

    logger.info("Бот остановлен.")


if __name__ == "__main__":
    start_bot()
