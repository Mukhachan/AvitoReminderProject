from DataBase import DataBase
from config import host, user, password, db_name
from datetime import *
import asyncio
import aiogram
import pymysql
import pymysql.cursors

# Подключаемся к бд и получаем экземпляр класса DataBase в лице "conn" #
conn = None
def db_connect():
    try:
        global conn 
        db = pymysql.connect(
            host = host,
            port = 3306,
            user = user,
            password = password,
            database = db_name,
            cursorclass = pymysql.cursors.DictCursor
        )
        conn = DataBase(db)
    except Exception as ex:
        print("[INFO] Ошибка при работе с MySQL: ", ex)
    return conn


"""
Теперь для подключения к бд надо вызвать функцию db_connect(). 
А если надо вызвать какой то метод из класса DataBase, пишешь conn.`название функции(аргументы)`
"""

async def check_database_changes():
    while True:
        try:
            # Отправить запрос на получение времени последнего изменения
            
            """
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(last_updated) FROM my_table;")
            last_updated = cursor.fetchone()[0]
            

            # Сравнить время последнего изменения с текущим временем
            if last_updated >= datetime.now() - timedelta(hours=1):
                # Отправить уведомление через Telegram API
                bot = aiogram.Bot("TOKEN")
                await bot.send_message(chat_id="CHAT_ID", text="База данных была изменена!")
            """
            
        except (pymysql.DatabaseError, aiogram.exceptions.TelegramAPIError) as e:
            # Обрабатывать ошибки
            print(e)

        # Ждём 1 час перед повторной проверкой базы данных
        await asyncio.sleep(3600)

# Запустить цикл проверки базы данных
loop = asyncio.get_event_loop()
loop.create_task(check_database_changes())
loop.run_forever()
