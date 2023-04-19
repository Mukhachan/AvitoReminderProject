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

def split_list(raw_links, cores):
    n = math.ceil(len(raw_links) / cores)

    for x in range(0, len(raw_links), n):
        e_c = raw_links[x : n + x]

        if len(e_c) < n:
            e_c = e_c + [None for y in range(n - len(e_c))]
        yield e_c


def start_threads(links):
    for i in range(cores):
        thread = threading.Thread(target=parser, args=(links[i],))
        thread.start()


links = list(split_list(raw_links, cores))

start_threads(links)'''

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
