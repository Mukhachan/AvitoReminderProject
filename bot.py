from config import bot_api_token, parser_timer, garbage_collector_time, mes_len, db_connect_pool, db_connect_old
from datetime import *
from aiogram import Bot, Dispatcher, types, executor
from aiogram.utils import *
import asyncio
import time
from backend import AvitoRequest
from DataBase import DataBase
from os import system
# Подключаемся к бд и получаем экземпляр класса DataBase в лице "conn" #
bot = Bot(token=bot_api_token)
dp = Dispatcher(bot)

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    conn = db_connect_old()
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

    del conn

@dp.message_handler(commands=['dev'])
async def dev_message(message: types.Message):
    await message.answer(text='Над проектом работали:\n- Альмухаметов Артём (@Mukhachan_dev)\n- Ардашев Александр (@likeaatea)')

@dp.message_handler()
async def echo_message(message: types.Message):
    """ Эхо функция """
    print(str(message.chat.id), ':', message.text)

    if message.text == 'developers':
        text = 'Над проектом работали:\n- Альмухаметов Артём (@Mukhachan_dev)\n- Ардашев Александр (@likeaatea)'
        await bot.send_message(message.from_user.id, text)

    else:
        await bot.send_message(message.from_user.id, message.text)


async def parsing_data_filter(requests: list) -> tuple:
    """ 
        Функция фильтрации. Передаём сюда список с запросами
        requests это список из словарей
    """
    conn = db_connect_old()
    if requests == 'Список пуст':
        return ('Список пуст', False)
    print('Количество надо проверить товаров: ', len(requests))
    lst = []

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
        elif price_from <= price <= price_up_to: # Это если товар подходит по нужной цене #
            print('Товар', i, 'подходит, добавляю:', elem)
            lst.append(elem)
            conn.update_parsing_state(id = elem['id'], state='sent') # Обновляем состояние записи в parsing_data #
        else:
            print('Товар', i, 'НЕ подходит по цене\n')

    # Сортируем список по ключу "user_id"
    lst.sort(key=lambda x: x.get('user_id')) 
    result = []
    current_group = []
    current_user_id = None
    # создаём список из списков из словарей. В каждом подсписке лежат словари с одинаковыми ключами user_id #
    for item in lst: # пробегаемся по списку словарей с товарами #
        user_id = item.get('user_id')  # берём user_id из словаря # 
        if user_id != current_user_id: # если юзер_id не равен текущему  #
            if current_group: # если current_group не пустая # 
                result.append(current_group) # добавить в список result этот подсписок #
            current_group = [item]  
            current_user_id = user_id
        else: 
            current_group.append(item)
    if current_group:
        result.append(current_group)
    
    goods_list = ''
    for i in result: # Перебираем подсписки. i - это подсписок#
        chat_id = conn.get_bot_key(i[0]['user_id']) # берём chat_id из первого #
        
        for x in i: # Перебираем словари в каждом подсписки. x - это словарь #
            if goods_list.count('руб') != mes_len: # Если в сообщении набралось N товаров #
                goods_list += f'{x["title"]}\n{x["price"]} руб\n{x["link"]}\n\n' # прибавляем товар #
            else:
                if chat_id[0] == 'start_code': # Если пользователь не привязал тг мы не отправляем ничего #
                    print('У этого пользователся не привязан ТГ')
                elif chat_id[0] == 'chat_id': # Если ТГ привязан то отправляем сообщение #
                    print('Висылаю вот сюда ->', chat_id[1], 'вот это ->', goods_list)
                    await bot.send_message(chat_id=chat_id[1], text=goods_list, parse_mode = "html")
                else:
                    print('Такого пользователя нет походу...')

                goods_list = ''

        if chat_id[0] != 'start_code' or chat_id != None or goods_list != '' :
            await bot.send_message(chat_id=chat_id[1], text=goods_list, parse_mode = "html")
        goods_list = ''

    del conn
    
    print('[INFO] Всё сообщения отправлены')
    return ('Всё сообщения отправлены', True)


async def schedule_handler():
    """
        Функция запускающая парсер
    """
    while True:
        conn = db_connect_old()
            
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
        del conn

        await asyncio.sleep(parser_timer)


async def database_garbage_collector():
    """
        Функции очистки базы данных
    """
    while True:
        conn = db_connect_old()
        print('Запускаю функцию очистки базы данных...')
        print("Изменено состояний авторизации:", conn.check_user_last_online())
        conn.parsing_data_del_time()
        conn.del_parsing_data_without_requests(pd_len_after = 0)

        del conn
        await asyncio.sleep(garbage_collector_time)
        system('cls')

if __name__ == '__main__':
    print('Бот запущен\n')
    
    loop = asyncio.get_event_loop()
    loop.create_task(database_garbage_collector())
    loop.create_task(schedule_handler())
    loop.create_task(executor.start_polling(dp, skip_updates=True))
