from config import host, user, password, db_name, bot_api_token
from datetime import *
from aiogram import Bot, Dispatcher, types, executor
import asyncio

import pymysql
import pymysql.cursors

from DataBase import DataBase
from backend import AvitoRequest

CORES = 1

# Подключаемся к бд и получаем экземпляр класса DataBase в лице "conn" #
parser = AvitoRequest
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
                x = conn.get_userid_by_bot_key(bot_key=start_code)
                x = conn.set_bot_key(tg_id=chat_id)

                if x[1] == True:
                    await message.answer(f'Бот успешно привязан!')
                elif x[1] == False:
                    await message.answer(f'{x[0]}')
        except Exception as e:
            print(e)
            await message.answer("Вы не зарегестрированны, зайдите по своей персональной ссылке")


async def parsing_data_filter(requests: list) -> bool:
    """ Функция фильтрации передаём туда список с запросами
        requests это список из словарей
    """
    async for i in requests: # Перебираем все словари(записи) и фильтруем #  
        if i['state'] == 'added':
            chat_id = await conn.get_bot_key(i['user_id']) # Получаем id чата в который надо отправить запись #
            text = 'Появились новые товары среди ваших отслеживаемых!\n', i['title'], i['price'], i['link']

            await bot.send_message(chat_id=chat_id, text=text) # отправляем сообщение юзеру #
            
            await conn.update_parsing_state(id = i['id'], state='sent') # Обновляем состояние записи в parsing_data #
        elif i['state'] == 'sent':
            print(str(i['id']), 'Уже отправлялась ранее')

    print('[INFO] Всё сообщения отправлены')

async def schedule_handler(message: types.Message):
    while True:
        await parser.main(cores=CORES) # Вызываем парсер и передаём количество потоков #
            # Вызываем функцию фильтрации, передаём данные из paring_data #
        await parsing_data_filter(requests = conn.parsing_data_read()) 

        await asyncio.sleep(3600)

dp.register_message_handler(schedule_handler, commands=["schedule"])


"""
Теперь для подключения к бд надо вызвать функцию db_connect(). 
А если надо вызвать какой то метод из класса DataBase, пишешь conn.`название функции(аргументы)`
"""
if __name__ == '__main__':
    print('Бот запущен')
    conn = db_connect()
    print('[INFO]: База Данных: ',conn)
    loop = asyncio.get_event_loop()
    loop.create_task(executor.start_polling(dp, skip_updates=True))
