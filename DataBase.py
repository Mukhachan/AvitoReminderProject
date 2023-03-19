from config import host, user, password, db_name
from werkzeug.security import generate_password_hash, check_password_hash

import pymysql

class DataBase:
    def __init__(self, db):
        self.__connection = db
        self.__cur = db.cursor()

    def create_table(self) -> bool:
        '''Вспомогательная функция для создания таблиц бд'''
        try:
            db = self.__connection
            with open('sq_db.sql', mode='r') as f:
                self.__cur.executescript(f.read())
            db.commit()
            db.close()
            print('Таблица создана')
            return True  
        except:    
            return False  

    def db_close(self) -> bool:
        try:
            print('[INFO] Закрытие соединения с БД MYSQL')
            self.__connection.close()
            return True
        except:
            print('[INFO] Не удалось закрыть БД')
            return False

    def create_user(self, email: (str), password: (str)) -> bool:
        """ Эта функция служит для создания пользователя """

        # хешируем пароль #
        password = generate_password_hash(password)
        self.__cur.execute(f"SELECT * FROM `avitoreminder`.`users` WHERE email = '{email}'")

        if self.__cur.fetchone():
            print('Такой пользователь уже зарегестрирован')
            return False
        
        try:
            """ Создаём запись в таблице users """
            sql_request = f"INSERT INTO `avitoreminder`.`users` (email, password) VALUES ({email}, {password})"

            self.__cur.execute(sql_request)
            self.__connection.commit()
            return True

        except pymysql.err as Error:
            print('[INFO] Возникла ошибка')
            print(Error)
            return False

    def parsing_data_read(self, id:(int)) -> list:
        """
            Собираем все данные с таблицы parsing_data
        """
        try:
            self.__cur.execute(f"SELECT * FROM `avitoreminder`.`parsing_data` WHERE user_id = {id}")
            res = self.__cur.fetchall()

            return res if res else None
        
        except:
            print('Ошибка при чтении БД (parsing_data)')
        
    def parsing_data_add(self, user_id:(int), link:(str), title:(str), price:(int)):
        """ 
        Функция используется для добавления данных в таблицу parsing_data, после парсинга Авито
        """