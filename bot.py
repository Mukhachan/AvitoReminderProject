from config import bot_api_token, cores
from datetime import *
from aiogram import Bot, Dispatcher, types, executor
import asyncio


from DataBase import DataBase
from backend import AvitoRequest
from db_connect import db_connect



# Подключаемся к бд и получаем экземпляр класса DataBase в лице "conn" #
parser = AvitoRequest
conn = db_connect()
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


@dp.message_handler() # Просто Эхо для проверки бота # 
async def echo_message(message: types.Message):
    print(str(message.chat.id), ':', message.text)
    await bot.send_message(message.from_user.id, message.text)


async def parsing_data_filter(requests: list) -> tuple:
    """ Функция фильтрации. Передаём сюда список с запросами
        requests это список из словарей
    """
    if requests == 'Список пуст':
        return ('Список пуст', False)
    print('Количество собщение должно отправится: ', len(requests))

    for i, elem in enumerate(requests): # Перебираем все словари(записи) и фильтруем #  
        print('Пробую отправить: ', i)
        if elem['state'] == 'added':
            print('ID пользователя:', elem['user_id'])
            chat_id = conn.get_bot_key(elem['user_id']) # Получаем id чата в который надо отправить запись #
            
            if chat_id == None:
                print('Такого пользователя нет или ещё что-то.\nЕдем дальше')
                continue

            text = f'Появились новые товары среди ваших отслеживаемых! \n{elem["title"]}\n{elem["price"]} руб\n\n{elem["link"]}'
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="html") # отправляем сообщение юзеру #
            conn.update_parsing_state(id = elem['id'], state='sent') # Обновляем состояние записи в parsing_data #

        elif elem['state'] == 'sent':
            print(str(elem['id']), 'Уже отправлялась ранее')

    print('[INFO] Всё сообщения отправлены')
    return ('Всё сообщения отправлены', True)

async def schedule_handler():
    while True:
        print('Запускаю парсер')
        await parser.main(cores=cores) # Вызываем парсер и передаём количество потоков #
            # Вызываем функцию фильтрации, передаём данные из paring_data #
        await parsing_data_filter(requests = conn.parsing_data_read()) 

        await asyncio.sleep(2700)



"""
Теперь для подключения к бд надо вызвать функцию db_connect(). 
А если надо вызвать какой то метод из класса DataBase, пишешь conn.`название функции(аргументы)`
"""
if __name__ == '__main__':
    print('Бот запущен\n')
    conn = db_connect()
    print('[INFO]: База Данных: ', conn)
    
    loop = asyncio.get_event_loop()

    loop.create_task(schedule_handler())
    loop.create_task(executor.start_polling(dp, skip_updates=True))
