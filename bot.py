from config import bot_api_token, cores, parser_timer, db_connect_pool, db_connect_old
from datetime import *
from aiogram import Bot, Dispatcher, types, executor
from aiogram.utils import *
import asyncio
import time
from backend import AvitoRequest
from DataBase import DataBase

# Подключаемся к бд и получаем экземпляр класса DataBase в лице "conn" #
bot = Bot(token=bot_api_token)
dp = Dispatcher(bot)


@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    try:
        start_code = message.text.split()
        chat_id = str(message.chat.id)
        
        print('Чат ID', chat_id, type(chat_id))
    except:
        return    

    if len(start_code) == 1: # Проверяем наличие старткода #
        print('Нет старткода. Обычный запуск...')
        await message.answer('Нет старткода')
        return

    start_code = start_code[1]
    print('Старткод', start_code, type(start_code))
    try:
        # Проверка наличия чат ID в бд
        await message.answer(f'Ваш чат ID: {chat_id}')
        # Передаём чат ID и проверяем. Есть ли он в бд #
        check = conn.get_userid_by_bot_key(bot_key=chat_id)
        print('user_id:', check)

        if check[1] == True: # Чат уже привязан к другому акку #
            print('Данный чат уже привязан к другому аккаунту')
            await message.answer('Данный чат уже привязан к другому аккаунту')

        elif check[1] == False: # Чат ещё не привязан к аккаунту #
            check = conn.get_userid_by_bot_key(bot_key=start_code) # Проверяем есть ли в БД старткод #
            print('Проверяем есть ли в БД старткод', check)
            if check[1] == True: # Если есть, то привязываем аккаунт #
                conn.set_bot_key(bot_key=start_code, tg_id=chat_id)
                print('Бот привязан к чату:', chat_id)
                await message.answer(f'Бот успешно привязан!')

    except Exception as e:
        print(e)
        await message.answer("Вы не зарегистрированны, зайдите по своей персональной ссылке")


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
    print('Количество сообщений должно отправится: ', len(requests))

    for i, elem in enumerate(requests): # Перебираем все словари(записи) и фильтруем #  
        
        if elem['state'] == 'sent':
            continue

        chat_id = conn.get_bot_key(elem['user_id'])[1] # Получаем id чата в который надо отправить запись #

        req = conn.get_request(elem['request_id']) # Получаем список с запросом для проверки данных через фильтр #

        price_from = 0 if req['price_from'] == None else req['price_from'] # Берём цену от #
        price_up_to = 999999999999999  if req['price_up_to'] == None else req['price_up_to'] # Берём верхнюю цену #
        
        price = elem['price']

        if chat_id == None:
            print('Такого пользователя нет или ещё что-то.\nЕдем дальше')
            continue

        elif price_from <= price <= price_up_to: # Проверяем. Подходит ли товар по нужной цене #
            print('ПРОБУЮ ОТПРАВИТЬ: ', i)
            text = f'\nПоявились новые товары среди ваших отслеживаемых! \n{elem["title"]}\n{elem["price"]} руб\n\n{elem["link"]}'
            try:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode="html") # отправляем сообщение юзеру #
            except:
                asyncio.sleep(5)

            conn.update_parsing_state(id = elem['id'], state='sent') # Обновляем состояние записи в parsing_data #
        else:
            print('Товар', i, 'НЕ подходит по цене\n')


    print('[INFO] Всё сообщения отправлены')
    return ('Всё сообщения отправлены', True)


async def schedule_handler():
    while True:
        print('Запускаю парсер')
        start = time.time()
        print('Запускаю таймер', start)
        DBase = DataBase
        db_pool = db_connect_pool()
        parser = AvitoRequest(DBase, db_pool)
        parser.main() # Вызываем парсер и передаём количество потоков #
            # Вызываем функцию фильтрации, передаём данные из paring_data #

        await parsing_data_filter(requests = conn.parsing_data_read()) 
        end =  time.time() - start
        print('Общее время работы парсера и отправки сообщений', end)
        del DBase
        del db_pool

        await asyncio.sleep(parser_timer)
if __name__ == '__main__':
    print('Бот запущен\n')
    
    conn = db_connect_old()
    print('[INFO] База Данных: ', conn)
    
    loop = asyncio.get_event_loop()
    loop.create_task(schedule_handler())
    loop.create_task(executor.start_polling(dp, skip_updates=True))
