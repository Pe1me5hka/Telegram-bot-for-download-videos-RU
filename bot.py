import os
import re
import asyncio
import logging
import sys
from concurrent.futures import ThreadPoolExecutor

from deps import bootstrap
bootstrap()

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.markdown import hlink
from yt_dlp import YoutubeDL

logging.basicConfig(level=logging.INFO)

# ==================== НАСТРОЙКА ТОКЕНА ПРЯМО ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(BASE_DIR, "token.txt")

if not os.path.exists(TOKEN_FILE):
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write("ВАШ_ТОКЕН_ТЕЛЕГРАМ_БОТА")
    logging.error(f"❌ Файл {TOKEN_FILE} не найден! Я создал его, вставьте туда токен и перезапустите бота.")
    sys.exit(1)

with open(TOKEN_FILE, "r", encoding="utf-8") as f:
    BOT_TOKEN = f.read().strip()

if BOT_TOKEN == "ВАШ_ТОКЕН_ТЕЛЕГРАМ_БОТА" or not BOT_TOKEN:
    logging.error(f"❌ Вы не указали токен бота в файле {TOKEN_FILE}!")
    sys.exit(1)
# ======================================================================

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Включаем HTML-поformatting для красивого отображения ссылок
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

thread_pool = ThreadPoolExecutor(max_workers=5)
sent_messages_log = []

HTTP_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}
EXTRACTOR_ARGS = {}

class BotModes(StatesGroup):
    video_mode = State()
    audio_mode = State()

video_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="/v"), KeyboardButton(text="/m")],
        [KeyboardButton(text="🧹 Очистить чат бота")]
    ],
    resize_keyboard=True,
    input_field_placeholder="📹 Сейчас включен РЕЖИМ ВИДЕО..."
)

audio_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="/v"), KeyboardButton(text="/m")],
        [KeyboardButton(text="🧹 Очистить чат бота")]
    ],
    resize_keyboard=True,
    input_field_placeholder="🎵 Сейчас включен РЕЖИМ MP3..."
)

def register_msg(msg: types.Message):
    if msg:
        sent_messages_log.append((msg.chat.id, msg.message_id))

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.set_state(BotModes.video_mode)
    res = await message.answer(
        "👋 Привет! Я быстрый асинхронный загрузчик.\n\n"
        "🟢 Режим: Видео\n"
        "📹 `/v` — Видео | 🎵 `/m` — MP3\n"
        "🧹 Нажмите кнопку ниже, чтобы удалить отправленные мной медиафайлы.",
        reply_markup=video_keyboard
    )
    register_msg(res)

@dp.message(Command("v"))
async def switch_to_video(message: types.Message, state: FSMContext):
    await state.set_state(BotModes.video_mode)
    res = await message.answer("📹 Режим скачивания video активен.", reply_markup=video_keyboard)
    register_msg(res)

@dp.message(Command("m"))
async def switch_to_audio(message: types.Message, state: FSMContext):
    await state.set_state(BotModes.audio_mode)
    res = await message.answer("🎵 Режим скачивания MP3 активен.", reply_markup=audio_keyboard)
    register_msg(res)

@dp.message(F.text == "🧹 Очистить чат бота")
@dp.message(Command("clear"))
async def clear_bot_chat(message: types.Message):
    if not sent_messages_log:
        await message.answer("Чистить нечего, история отправленных файлов пуста! 👍")
        return

    status = await message.answer("🧹 Начинаю удаление медиафайлов из чата...")
    deleted_count = 0
    
    for chat_id, msg_id in reversed(sent_messages_log):
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            deleted_count += 1
        except Exception:
            pass

    sent_messages_log.clear()
    await status.edit_text(f"✨ Готово! Удалено сообщений: {deleted_count}. Чат очищен.")
    await asyncio.sleep(5)
    try:
        await status.delete()
        await message.delete()
    except Exception:
        pass

# --- АСИНХРОННАЯ ФУНКЦИЯ-ОБРАБОТЧИК ОДНОГО ВИДЕО ---
async def process_single_video(message: types.Message, url: str, index: int, total: int):
    status_message = await message.answer(f"⏳ [{index}/{total}] Начинаю загрузку видео...")
    register_msg(status_message)
    filename = None
    try:
        ydl_opts = {
            'format_sort': ['res:720', 'ext:mp4:m4a'],
            'merge_output_format': 'mp4',
            'outtmpl': os.path.join(DOWNLOAD_DIR, f'%(id)s_video_{index}.%(ext)s'),
            'max_filesize': 50 * 1024 * 1024,
            'quiet': True,
            'nocheckcertificate': True,
            'page_agnostic': True,
            'http_headers': HTTP_HEADERS,
            'extractor_args': EXTRACTOR_ARGS,
        }

        loop = asyncio.get_running_loop()
        
        def download():
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info)

        filename = await loop.run_in_executor(thread_pool, download)
            
        if not os.path.exists(filename):
            base, _ = os.path.splitext(filename)
            filename = base + ".mp4"

        await status_message.edit_text(f"📤 [{index}/{total}] Отправляю файл в Telegram...")
        res_video = await message.answer_video(video=FSInputFile(filename), caption=f"Видео #{index}")
        register_msg(res_video)
        await status_message.delete()

    except Exception as e:
        logging.error(f"❌ Ошибка (Видео) {url}: {e}")
        error_text = str(e)
        
        # Исправлено: проверки теперь находятся строго внутри блока except
        if "HTTP Error 403" in error_text:
            await status_message.edit_text(
                f"❌ <b>Ошибка 403 (Ограничение YouTube)</b>\n"
                f"Не удалось скачать видео #{index}.\n\n"
                f"Ссылка:\n<code>{url}</code>"
            )
        elif "File is larger than max-filesize" in error_text:
            await status_message.edit_text(
                f"❌ <b>Файл слишком большой (более 50 МБ)</b>\n"
                f"Не удалось скачать видео #{index}.\n\n"
                f"Ссылка:\n<code>{url}</code>"
            )
        else:
            await status_message.edit_text(
                f"❌ <b>Ошибка скачивания видео #{index}</b>\n"
                f"Проверьте ссылку или попробуйте позже.\n\n"
                f"Ссылка:\n<code>{url}</code>"
            )
            
    finally:
        # Исправлено: автоматическая очистка скачанного файла после отправки или ошибки
        if filename and os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass


# --- АСИНХРОННАЯ ФУНКЦИЯ-ОБРАБОТЧИК ОДНОГО АУДИО ---
async def process_single_audio(message: types.Message, url: str, index: int, total: int):
    status_message = await message.answer(f"⏳ [{index}/{total}] Извлекаю аудио...")
    register_msg(status_message)
    filename = None
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(DOWNLOAD_DIR, f'%(id)s_audio_{index}.%(ext)s'),
            'quiet': True,
            'nocheckcertificate': True,
            'page_agnostic': True,
            'http_headers': HTTP_HEADERS,
            'extractor_args': EXTRACTOR_ARGS,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }

        loop = asyncio.get_running_loop()
        
        def download():
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                base, _ = os.path.splitext(filename)
                return base + ".mp3"

        filename = await loop.run_in_executor(thread_pool, download)

        await status_message.edit_text(f"📤 [{index}/{total}] Отправляю MP3...")
        res_audio = await message.answer_audio(audio=FSInputFile(filename), caption=f"Аудио #{index}")
        register_msg(res_audio)
        await status_message.delete()

    except Exception as e:
        logging.error(f"❌ Ошибка (Аудио) {url}: {e}")
        pretty_url = hlink(f"аудио #{index}", url)
        
        if "HTTP Error 403" in str(e):
            await status_message.edit_text(f"❌ <b>Ошибка 403 (Ограничение YouTube)</b>\nНе удалось извлечь {pretty_url}")
        else:
            await status_message.edit_text(f"❌ Ошибка скачивания {pretty_url}.")
    finally:
        if filename and os.path.exists(filename):
            os.remove(filename)

@dp.message(BotModes.video_mode, F.text)
async def handle_video_links(message: types.Message):
    if message.text.startswith('/'): return
    urls = list(dict.fromkeys(re.findall(r'https?://.+?(?=https?://|\s|$)', message.text)))
    if not urls:
        await message.answer("❌ В этом режиме отправляйте только прямые ссылки на видео.")
        return
        
    await message.answer(f"🔍 Найдено ссылок: {len(urls)}. Запускаю параллельное скачивание...")
    tasks = [process_single_video(message, url, i, len(urls)) for i, url in enumerate(urls, start=1)]
    await asyncio.gather(*tasks)

@dp.message(BotModes.audio_mode, F.text)
async def handle_audio_links(message: types.Message):
    if message.text.startswith('/'): return
    urls = list(dict.fromkeys(re.findall(r'https?://.+?(?=https?://|\s|$)', message.text)))
    if not urls:
        await message.answer("❌ В этом режиме отправляйте только прямые ссылки для извлечения аудио.")
        return
        
    await message.answer(f"🔍 Найдено ссылок: {len(urls)}. Запускаю параллельное извлечение...")
    tasks = [process_single_audio(message, url, i, len(urls)) for i, url in enumerate(urls, start=1)]
    await asyncio.gather(*tasks)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
