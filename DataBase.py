import psycopg2
from config import host, user, password, db_name

class DataBase:
    def __init__(self):
        try:
            __connection = psycopg2.connect(
                host = host,
                user = user,
                password = password,
                batabase = db_name
            )
        except Exception as ex:
            print("[INFO] Ошибка при работе с PostgreSQL: ", ex)

    def db_connect(self):
        try:
            __connection = psycopg2.connect(
                host = host,
                user = user,
                password = password,
                batabase = db_name
            )
        except Exception as ex:
            print("[INFO] Ошибка при работе с PostgreSQL: ", ex)

    def db_close(self):
        print('[INFO] Закрытие соединения с БД PostrgreSQL')
        self.__connection.close()