import psycopg2
from config import host, user, password, db_name

class DataBase:
    def __init__(self, db):
        self.__connection = db
        self.__cur = db.cursor()

    
    def db_close(self):
        print('[INFO] Закрытие соединения с БД PostrgreSQL')
        self.__connection.close()