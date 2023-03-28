from config import host, user, password, db_name, bot_api_token
from datetime import *
from aiogram import Bot, Dispatcher, types, executor
import asyncio
import aiogram
import pymysql
import pymysql.cursors
from DataBase import DataBase

# Подключаемся к бд и получаем экземпляр класса DataBase в лице "conn" #

def db_connect():
    try:
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


bot = Bot(token=bot_api_token)
dp = Dispatcher(bot)

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    start_code = message.text.split()
    chat_id = str(message.chat.id)
    
    print('Чат ID', chat_id, type(chat_id))
    if len(start_code) == 1:
        print('Обычный запуск')
        await message.answer('Нет старткода')
    else:
        start_code = start_code[1]
        print('Старткод', start_code, type(start_code))
        try:
            if start_code == "12dev34":
                await message.answer("разрабы идут нахуй")
            elif start_code == "444555666":
                await message.answer(text= f'Вы успешно вошли в бд под логином "Paul" \nЧат ID: {chat_id}') #после правок имя сменится на переменную
                
            else:
                # Проверка наличия юзер кода в бд
                await message.answer(f'Ваш чат ID: {chat_id}')
                #conn.get_userid_set_bot_key(bot_key=start_code, tg_id=chat_id) # ОНО НЕ РАБОТАЕТ #
        except Exception as e:
            print(e)
            await message.answer("Вы не зарегестрированны, зайдите по своей персональной ссылке")


"""
Теперь для подключения к бд надо вызвать функцию db_connect(). 
А если надо вызвать какой то метод из класса DataBase, пишешь conn.`название функции(аргументы)`
"""

async def check_database_changes():
    print('Расписание запущено')
    while True:
        try:
            # Отправить запрос на получение времени последнего изменения
            
            """
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

if __name__ == '__main__':
    print('Бот запущен')
    conn = db_connect()
    print(conn)
    loop = asyncio.get_event_loop()
    loop.create_task(executor.start_polling(dp, skip_updates=True))
    loop.run_forever()
    
    print('Ну и пошёл нахуй, пидор')