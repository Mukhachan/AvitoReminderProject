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
def update_record(id: int, title: str | None, price_from: int | None,
                                price_up_to: int | None, city: str | None, add_description: str | None,
                                delivery: int | None, exception: str | None):
    update_fields = []
    if title is not None:
        update_fields.append("title = '{}'".format(title))
    if price_from is not None:
        update_fields.append("price_from = '{}'".format(price_from))
    if price_up_to is not None:
        update_fields.append("price_up_to = '{}'".format(price_up_to))
    if city is not None:
        update_fields.append("city = '{}'".format(city))
    if add_description is not None:
        update_fields.append("add_description = '{}'".format(add_description))
    if delivery is not None:
        update_fields.append("delivery = '{}'".format(delivery))
    if exception is not None:
        update_fields.append("exception = '{}'".format(exception))

    if not update_fields:
        # ничего изменять не нужно
        return

    update_query = "UPDATE `avitoreminder`.`requests` SET {} WHERE id = {}".format(
        ", ".join(update_fields), id)

    # выполнить SQL-запрос в базе данных
    # connection.execute(update_query)
def update_record(id: int, title = None, price_from = None, price_up_to = None, 
                  city = None, add_description = None, delivery = None, exception = None):
    update_fields = []

    for field in ['title', 'price_from', 'price_up_to', 'city', 'add_description', 'delivery', 'exception']:
        if locals()[field] is not None:
            update_fields.append(f"{field} = '{locals()[field]}'")

    if not update_fields:
        return

    update_query = f"UPDATE `avitoreminder`.`requests` SET {', '.join(update_fields)} WHERE id = {id}"