from telegram import ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, ConversationHandler, MessageHandler, filters, PicklePersistence
from dotenv import load_dotenv
import requests
import os
import logging

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

# Конфигурация
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
UNSPLASH_ACCESS_KEY = os.getenv('UNSPLASH_ACCESS_KEY')
BASE_URL = 'https://api.unsplash.com'
APP_NAME = 'SplashBot'

HEADERS = {
    'Authorization': f'Client-ID {UNSPLASH_ACCESS_KEY}',
    'Accept-Version': 'v1'
}

# Стадии для ConversationHandler
MAIN_MENU, RANDOM_PHOTO, SEARCH_INPUT, SEARCH_RESULT, COLLECTIONS_MENU, COLLECTION_RESULT = range(6)

# Меню
MAIN_MENU_OPTIONS = [["🖼️ Случайное фото"], ["🔍 Поиск фото"], ["📁 Коллекции"]]


def get_unsplash_photos(endpoint, params=None):
    try:
        response = requests.get(f'{BASE_URL}/{endpoint}', headers=HEADERS, params=params or {})
        response.raise_for_status()
        remaining = int(response.headers.get('X-Ratelimit-Remaining', 50))
        if remaining < 10:
            logger.warning(f"Осталось мало запросов: {remaining}")
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка API Unsplash: {str(e)}")
        raise Exception(f"Ошибка API: {str(e)}")


def trigger_download(download_url):
    try:
        requests.get(download_url, headers=HEADERS)
    except requests.exceptions.RequestException as e:
        logger.warning(f"Ошибка при скачивании: {str(e)}")


class UnsplashBot:
    def __init__(self):
        self.search_queries = {}

    def get_attribution(self, photo):
        profile_url = f"{photo['user']['links']['html']}?utm_source={APP_NAME}&utm_medium=referral"
        return f"Фото от <a href='{profile_url}'>{photo['user']['name']}</a> на Unsplash"

    async def start(self, update, context):
        reply_markup = ReplyKeyboardMarkup(MAIN_MENU_OPTIONS, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text('Добро пожаловать! Выберите действие:', reply_markup=reply_markup)
        return MAIN_MENU

    async def main_menu(self, update, context):
        text = update.message.text.strip()
        if text == "🖼️ Случайное фото":
            return await self.random_photo(update, context)
        elif text == "🔍 Поиск фото":
            return await self.search_menu(update, context)
        elif text == "📁 Коллекции":
            return await self.collections_menu(update, context, page=1)
        else:
            await update.message.reply_text("Пожалуйста, выберите действие из меню.")
            return MAIN_MENU

    async def random_photo(self, update, context):
        try:
            photo = get_unsplash_photos('photos/random')
            trigger_download(photo['links']['download_location'])
            reply_markup = ReplyKeyboardMarkup(
                [["Еще фото"], ["Назад"]],
                resize_keyboard=True,
                one_time_keyboard=True
            )
            await update.message.reply_photo(
                photo=photo['urls']['regular'],
                caption=self.get_attribution(photo),
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
            return RANDOM_PHOTO
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {str(e)}")
            return MAIN_MENU

    async def handle_random_photo(self, update, context):
        text = update.message.text.strip()
        if text == "Еще фото":
            return await self.random_photo(update, context)
        elif text == "Назад":
            reply_markup = ReplyKeyboardMarkup(MAIN_MENU_OPTIONS, resize_keyboard=True)
            await update.message.reply_text('Выберите действие:', reply_markup=reply_markup)
            return MAIN_MENU
        else:
            await update.message.reply_text("Пожалуйста, выберите действие из меню.")
            return RANDOM_PHOTO

    async def search_menu(self, update, context):
        chat_id = update.message.chat_id
        self.search_queries[chat_id] = ''
        reply_markup = ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
        await update.message.reply_text('Введите ключевые слова для поиска:', reply_markup=reply_markup)
        return SEARCH_INPUT

    async def handle_search_input(self, update, context):
        chat_id = update.message.chat_id
        text = update.message.text.strip()
        if text == "Назад":
            reply_markup = ReplyKeyboardMarkup(MAIN_MENU_OPTIONS, resize_keyboard=True)
            await update.message.reply_text('Выберите действие:', reply_markup=reply_markup)
            return MAIN_MENU
        if chat_id in self.search_queries:
            context.user_data["search_query"] = text
            context.user_data["search_page"] = 1
            await self.show_search_results(update, context, text, 1)
            del self.search_queries[chat_id]
            return SEARCH_RESULT

    async def show_search_results(self, update, context, query, page):
        try:
            params = {'query': query, 'page': page, 'per_page': 1, 'order_by': 'relevant'}
            results = get_unsplash_photos('search/photos', params=params)
            if not results['results']:
                reply_markup = ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
                await update.message.reply_text("Фото не найдены.", reply_markup=reply_markup)
                return SEARCH_RESULT

            photo = results['results'][0]
            trigger_download(photo['links']['download_location'])
            context.user_data["total_pages"] = results['total_pages']

            reply_markup = ReplyKeyboardMarkup(
                [["⬅️ Предыдущее"], ["➡️ Следующее"], ["Назад"]],
                resize_keyboard=True
            )
            await update.message.reply_photo(
                photo=photo['urls']['regular'],
                caption=f"{self.get_attribution(photo)}\nСтраница {page} из {results['total_pages']}",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
            return SEARCH_RESULT
        except Exception as e:
            reply_markup = ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
            await update.message.reply_text(f"Ошибка: {str(e)}", reply_markup=reply_markup)
            return SEARCH_RESULT

    async def handle_search_result(self, update, context):
        text = update.message.text.strip()
        query = context.user_data.get("search_query")
        page = context.user_data.get("search_page", 1)
        total_pages = context.user_data.get("total_pages", 1)

        if text == "⬅️ Предыдущее" and page > 1:
            context.user_data["search_page"] = page - 1
            await self.show_search_results(update, context, query, page - 1)
        elif text == "➡️ Следующее" and page < total_pages:
            context.user_data["search_page"] = page + 1
            await self.show_search_results(update, context, query, page + 1)
        elif text == "Назад":
            reply_markup = ReplyKeyboardMarkup(MAIN_MENU_OPTIONS, resize_keyboard=True)
            await update.message.reply_text('Выберите действие:', reply_markup=reply_markup)
            return MAIN_MENU
        else:
            await update.message.reply_text("Пожалуйста, выберите действие из меню.")
        return SEARCH_RESULT

    async def collections_menu(self, update, context, page=1):
        try:
            params = {'page': page, 'per_page': 10}
            collections = get_unsplash_photos('collections', params=params)
            if not collections:
                reply_markup = ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
                await update.message.reply_text("Коллекции не найдены.", reply_markup=reply_markup)
                return COLLECTIONS_MENU

            context.user_data["collections"] = {c["title"]: c["id"] for c in collections}
            context.user_data["collections_page"] = page

            collection_titles = [[c["title"]] for c in collections]
            navigation = []
            if page > 1:
                navigation.append("⬅️ Предыдущая страница")
            navigation.append("➡️ Следующая страница")
            navigation.append("Назад")
            reply_markup = ReplyKeyboardMarkup(collection_titles + [navigation], resize_keyboard=True,
                                               one_time_keyboard=True)

            await update.message.reply_text(f'Выберите коллекцию (страница {page}):', reply_markup=reply_markup)
            return COLLECTIONS_MENU
        except Exception as e:
            reply_markup = ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
            await update.message.reply_text(f"Ошибка при загрузке коллекций: {str(e)}", reply_markup=reply_markup)
            return COLLECTIONS_MENU

    async def handle_collections_menu(self, update, context):
        text = update.message.text.strip()
        page = context.user_data.get("collections_page", 1)

        if text == "Назад":
            reply_markup = ReplyKeyboardMarkup(MAIN_MENU_OPTIONS, resize_keyboard=True)
            await update.message.reply_text('Выберите действие:', reply_markup=reply_markup)
            return MAIN_MENU
        elif text == "⬅️ Предыдущая страница" and page > 1:
            return await self.collections_menu(update, context, page - 1)
        elif text == "➡️ Следующая страница":
            return await self.collections_menu(update, context, page + 1)

        collections = context.user_data.get("collections", {})
        if text in collections:
            context.user_data["collection_id"] = collections[text]
            context.user_data["collection_title"] = text
            context.user_data["collection_page"] = 1
            await self.show_collection(update, context, collections[text], text, 1)
            return COLLECTION_RESULT
        await update.message.reply_text("Пожалуйста, выберите коллекцию или действие из меню.")
        return COLLECTIONS_MENU

    async def show_collection(self, update, context, collection_id, collection_title, page):
        try:
            params = {'page': page, 'per_page': 1}
            results = get_unsplash_photos(f'collections/{collection_id}/photos', params=params)
            logger.info(f"Ответ API для коллекции {collection_id}, страница {page}: {results}")

            if not results or len(results) == 0:
                reply_markup = ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
                await update.message.reply_text("Фото в коллекции не найдены.", reply_markup=reply_markup)
                return COLLECTION_RESULT

            photo = results[0]
            trigger_download(photo['links']['download_location'])

            collection_info = get_unsplash_photos(f'collections/{collection_id}')
            total_photos = collection_info.get('total_photos', 1)
            total_pages = (total_photos + params['per_page'] - 1) // params['per_page']
            context.user_data["total_pages"] = total_pages

            reply_markup = ReplyKeyboardMarkup(
                [["⬅️ Предыдущее"], ["➡️ Следующее"], ["Назад"]],
                resize_keyboard=True
            )
            await update.message.reply_photo(
                photo=photo['urls']['regular'],
                caption=f"Коллекция: {collection_title}\n{self.get_attribution(photo)}\nСтраница {page} из {total_pages}",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
            return COLLECTION_RESULT
        except Exception as e:
            reply_markup = ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)
            await update.message.reply_text(f"Ошибка: {str(e)}", reply_markup=reply_markup)
            return COLLECTION_RESULT

    async def handle_collection_result(self, update, context):
        text = update.message.text.strip()
        collection_id = context.user_data.get("collection_id")
        collection_title = context.user_data.get("collection_title")
        page = context.user_data.get("collection_page", 1)
        total_pages = context.user_data.get("total_pages", 1)

        if text == "⬅️ Предыдущее" and page > 1:
            context.user_data["collection_page"] = page - 1
            await self.show_collection(update, context, collection_id, collection_title, page - 1)
        elif text == "➡️ Следующее" and page < total_pages:
            context.user_data["collection_page"] = page + 1
            await self.show_collection(update, context, collection_id, collection_title, page + 1)
        elif text == "Назад":
            await self.collections_menu(update, context, context.user_data.get("collections_page", 1))
            return COLLECTIONS_MENU
        else:
            await update.message.reply_text("Пожалуйста, выберите действие из меню.")
        return COLLECTION_RESULT


async def cancel(update, context):
    reply_markup = ReplyKeyboardMarkup(MAIN_MENU_OPTIONS, resize_keyboard=True)
    await update.message.reply_text('Диалог завершен. Выберите действие:', reply_markup=reply_markup)
    return ConversationHandler.END


async def error_handler(update, context):
    logger.error(f"Произошла ошибка: {context.error}")
    if update and hasattr(update, 'message'):
        reply_markup = ReplyKeyboardMarkup(MAIN_MENU_OPTIONS, resize_keyboard=True)
        await update.message.reply_text("Произошла ошибка. Выберите действие:", reply_markup=reply_markup)


def main():
    persistence = PicklePersistence(filepath='bot_data.pkl')
    application = Application.builder().token(TOKEN).persistence(persistence).build()
    bot = UnsplashBot()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", bot.start)],
        states={
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.main_menu)],
            RANDOM_PHOTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_random_photo)],
            SEARCH_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_search_input)],
            SEARCH_RESULT: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_search_result)],
            COLLECTIONS_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_collections_menu)],
            COLLECTION_RESULT: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_collection_result)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
        persistent=True,
        name='unsplash_conversation'
    )

    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)

    application.run_polling()


if __name__ == '__main__':
    main()
