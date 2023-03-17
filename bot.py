#санечек, ебашь!!!!
#я рожден еашить
import asyncio
import aiogram
import psycopg2

# Установка соединения с базой данных
conn = psycopg2.connect(
    host="localhost",
    database="mydatabase",
    user="myusername",
    password="mypassword"
)

async def check_database_changes():
    while True:
        try:
            # Отправить запрос на получение времени последнего изменения
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(last_updated) FROM my_table;")
            last_updated = cursor.fetchone()[0]

            # Сравнить время последнего изменения с текущим временем
            if last_updated >= datetime.now() - timedelta(hours=1):
                # Отправить уведомление через Telegram API
                bot = aiogram.Bot("TOKEN")
                await bot.send_message(chat_id="CHAT_ID", text="База данных была изменена!")
        
        except (psycopg2.DatabaseError, aiogram.exceptions.TelegramAPIError) as e:
            # Обрабатывать ошибки
            print(e)

        # Ждать 1 час перед повторной проверкой базы данных
        await asyncio.sleep(3600)

# Запустить цикл проверки базы данных
loop = asyncio.get_event_loop()
loop.create_task(check_database_changes())
loop.run_forever()
