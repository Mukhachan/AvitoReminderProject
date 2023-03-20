from config import host, user, password, db_name
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet


import pymysql

class DataBase:
    def __init__(self, db):
        self.__connection = db
        self.__cur = db.cursor()
        self.__key = b'CDvuZAPOVQ-TJDIDp08-1Tm7OGoXOZvEAJ9-mQ4xLLI='
        self.__f = Fernet(self.__key)

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

    def create_user(self, email: str, password: str) -> bool:
        """ Эта функция служит для создания пользователя """

        # хешируем пароль #
        password = generate_password_hash(password)
        self.__cur.execute(f"SELECT * FROM `avitoreminder`.`users` WHERE email = '{email}'")

        if self.__cur.fetchone():
            print('Такой пользователь уже зарегестрирован')
            return False
        
        try:
            """ Создаём запись в таблице users """
            sql_request = f'INSERT INTO `avitoreminder`.`users` (email, password) VALUES ("{email}", "{password}")'
             
            self.__cur.execute(sql_request)
            self.__connection.commit()
             # Берём ID юзера #
            self.__cur.execute(f'SELECT id from `avitoreminder`.`users` WHERE email = "{email}"')
            id = self.__cur.fetchone()

             # Сохраняем зашифрованый ID в файл #
            with open('cfg.cfg', 'w+') as file:
                file.write(self.__f.encrypt(id))
            return True

        except pymysql.err as Error:
            print('[INFO] Возникла ошибка')
            print(Error)
            return False
        
    def get_user(self, email: str, password: str) -> tuple:
        """
            Функция авторизации пользователя. Возвращает кортеж в виде("ошибка", bool). 
                Есть пользователь или нет.
        """

        # Проверяем есть ли пользователь с такой почтой #
        try:
            self.__cur.execute(f'SELECT email from `avitoreminder`.`users` WHERE email = "{email}"')
            res = self.__cur.fetchall()
            if res:
                pass
            else: 
                return ('Такой пользователь не найден', False)
        except:
            print('[INFO] Возникла ошибка')
        
        self.__cur.execute(f'SELECT * from `avitoreminder`.`users` WHERE email = "{email}"')
        res = self.__cur.fetchall()
        hash_psw = (list(res[0])[2])
        if check_password_hash(hash_psw, password):
            return ("Успешная авторизация", True)
        else:
            return("Неверный пароль", False)

    def parsing_data_read(self, id: int) -> list:
        """
            Собираем все данные с таблицы parsing_data
        """
        try:
            self.__cur.execute(f"SELECT * FROM `avitoreminder`.`parsing_data` WHERE user_id = '{id}'")
            res = self.__cur.fetchall()

            return res if res else None
        
        except:
            print('Ошибка при чтении БД (parsing_data)')
        
    def parsing_data_add(self, user_id: int, link: str, title: str, price: int) -> list:
        """ 
        Функция используется для добавления данных в таблицу parsing_data, после парсинга Авито
        """

        try:
            self.__cur.execute(
            f'INSERT INTO `avitoreminder`.`parsing_data` VALUES (NULL, "{user_id}", "{link}", "{title}", "{price}")'
               )
            self.__connection.commit()
            print("[INFO] Данные успешно добавлены")
        except:
            print('[INFO] Возникла ошибка при добавлении данных в таблицу parsing_data')
    
    def set_user_state(self, key: str) -> bool:
        """
            Устанавливаем состояние авторизации пользователя.
            Если в таблице нет такого пользователя, мы его создаём и сохраняем все данные.
            Если пользователь есть, то обновляем данные 
        """
        # Я ваш шифратор в рот ебал #
        

    def get_user_state(self):
        """
            Получаем состояние авторизации пользователя
        """