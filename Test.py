'''import threading
import math

from config import cores, db_connect

cores = 2
raw_links = db_connect().get_requests()

print(len(raw_links))

def parser(links):
    """
        Это типо парсер будет
    """
    for link in links:
        if link != None:
            print('Собираю данные по ссылке:', link)
        else:
            print('None, так что скипаю')

def start_threads(links):
    for i in range(cores):
        thread = threading.Thread(target=parser, args=(links[i],))
        thread.start()


links = list(split_list(raw_links, cores))

start_threads(links)'''
"""
from mysql.connector.pooling import MySQLConnectionPool
from config import db_connect_pool


class DataBase:
    def __init__(self, connection = None, cursor = None) -> None:
        self.__connection = connection
        self.__cur = cursor

    def function(self):
        self.__cur.close()
        self.__connection.close()
        print('Соединение и курсор вроде как закрыты')

    def __del__(self):
        print('Уничтожаем соединение и курсор')

class AvitoRequest:
    def __init__(self, Dbase: DataBase, db_pool: MySQLConnectionPool) -> None:
        self.DBase = Dbase
        self.pool = db_pool

    def function(self):
        connection = self.pool.get_connection()
        cursor = connection.cursor()

        self.DBase(connection=connection, cursor=cursor).function()

parser = AvitoRequest(DataBase, db_connect_pool()).function()
"""
"""
id: int, title: str | None, price_from: int | None,
    price_up_to: int | None, city: str | None, add_description: str | None,
                                delivery: int | None, exception: str | None
"""

"""
    conn = db_connect_old()
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
            text = (
            f'\nПоявились новые товары среди ваших отслеживаемых! \n{elem["title"]}\n{elem["price"]} руб\n\n{elem["link"]}'
            )
            try:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode="html") # отправляем сообщение юзеру #
            except:
                asyncio.sleep(5)

            conn.update_parsing_state(id = elem['id'], state='sent') # Обновляем состояние записи в parsing_data #
        else:
            print('Товар', i, 'НЕ подходит по цене\n')
    del conn
"""