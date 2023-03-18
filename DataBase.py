import psycopg2
from config import host, user, password, db_name

class DataBase:
    def __init__(self, db):
        self.__connection = db
        self.__cur = db.cursor()

    def create_table(self):
        '''Вспомогательная функция для создания таблиц бд'''
        db = self.__connection
        with open('sq_db.sql', mode='r') as f:
            self.__cur.executescript(f.read())
        db.commit()
        db.close()
        print('БД подключена')    

    def db_close(self):
        print('[INFO] Закрытие соединения с БД PostrgreSQL')
        self.__connection.close()

    def add_user(self):
        """
        
        """

    def parsing_data_read(self):
        """
            Собираем все данные с таблицы parsing_data
        """
        try:
            self.__cur.execute("SELECT * FROM parsing_data")
            res = self.__cur.fetchall()

            return res if res else None
        
        except:
            print('Ошибка при чтении БД (parsing_data)')
        
        