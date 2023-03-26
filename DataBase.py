from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
from random import choice
import string
import datetime
import pymysql

class DataBase:
    def __init__(self, db): # Инициализация глобальных переменных # 
        self.__connection = db # Подключаемся к бд #
        self.__cur = db.cursor() # Курсор для запросов в бд # 
        self.__key = b'mAJ_0ZIV4Y8FFVx5b-bfBpTNWsqv1hsxt-H5gHvXEYM=' # Ключ для шифровки файла cfg #
        self.__f = Fernet(self.__key) # Экземпляр класс Fernet #

    def create_table(self) -> bool: # Функция для создания таблиц #
        '''Вспомогательная функция для создания таблиц бд'''
        try:
            db = self.__connection
            with open('sq_db.sql', mode='r') as f:
                self.__cur.executescript(f.read()) # Выполняем запрос к бд #
            db.commit() # Сохраняем  #
            db.close() # Закрываем бд #
            print('Таблица создана')
            return True  
        except:    
            return False  

    def db_close(self) -> bool: # Закрытие БД #
        try:
            print('[INFO] Закрытие соединения с БД MYSQL')
            self.__connection.close()
            return True
        except:
            print('[INFO] Не удалось закрыть БД')
            return False

    def create_user(self, email: str, password: str) -> bool: # Функция для регистрации пользователя #
        """ Эта функция служит для создания пользователя """

        # хешируем пароль #
        password = generate_password_hash(password)
        self.__cur.execute(f"SELECT * FROM `avitoreminder`.`users` WHERE email = '{email}'")
        ex = self.__cur.fetchone()
        print(ex)
        if ex:
            print(ex)
            print('Такой пользователь уже зарегистрирован')
            return False
        
        try:
             # Создаём запись в таблице users #
            code = DataBase.create_start_code()
            sql_request = f'INSERT INTO `avitoreminder`.`users` (email, password, bot_key) VALUES ("{email}", "{password}", "{code}")'
             
            self.__cur.execute(sql_request)
            self.__connection.commit()
            print('Успешная регистрация')
             # Берём ID юзера #
            self.__cur.execute(f'SELECT id from `avitoreminder`.`users` WHERE email = "{email}"')
            
            id = str(self.__cur.fetchone()['id'])

             # Сохраняем зашифрованый ID в файл #
            with open('cfg.cfg', 'wb') as file:
                file.write(self.__f.encrypt(id.encode()))
            DataBase.set_user_state(self, id)
            print("Пользователь добавлен")
            return True
        except pymysql.err as Error:
            print('[INFO] Возникла ошибка')
            print(Error)
            return False
        
    def get_user(self, email: str, password: str) -> tuple: # Авторизация пользователя #
        """
            Функция авторизации пользователя. Возвращает кортеж в виде("описание", bool). 
                Есть пользователь или нет.
        """

        # Проверяем есть ли пользователь с такой почтой #
        try:
            self.__cur.execute(f'SELECT email from `avitoreminder`.`users` WHERE email = "{email}"')
            res = self.__cur.fetchone()
            if res:
                print('Пользователь найден')
            else: 
                return ('Такой пользователь не найден', False)
        except:
            print('[INFO] Возникла ошибка')
        
        self.__cur.execute(f'SELECT * from `avitoreminder`.`users` WHERE email = "{email}"')
        res = self.__cur.fetchone()
        id = str(res['id'])

        hash_psw = res['password']
        print(hash_psw)
        if check_password_hash(hash_psw, password):
            DataBase.set_user_state(self, id)
            print('Успешная авторизация')
            return ("Успешная авторизация", True)
        else:
            print("Неверный пароль")
            return("Неверный пароль", False)

    def parsing_data_add(self, user_id: int, link: str, title: str, price: int) -> list: # Добавление в parsing data #
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
 
    def parsing_data_read(self, id: int) -> list: # Чтение из parsing_data #
        """
            Собираем все данные с таблицы parsing_data
            Возвращает список из словарей
        """
        try:
            self.__cur.execute(f"SELECT * FROM `avitoreminder`.`parsing_data` WHERE user_id = '{id}'")
            res = self.__cur.fetchall()
            print(res)
            return res if res else None
        
        except:
            print('Ошибка при чтении БД (parsing_data)')
          
    def set_user_state(self, id: str) -> tuple: # Установка состояния авторизации #
        """
            Устанавливаем состояние авторизации пользователя.
            Если не найден файл cfg.cfg, то мы его создаём.
            Если в таблице нет такого пользователя, мы его создаём и сохраняем все данные.
            Если пользователь есть, то обновляем данные 
        """

            # Сохраняем зашифрованый ID в файл #
        with open('cfg.cfg', 'wb') as file:
            file.write(self.__f.encrypt(id.encode()))
        
        
        try:
            with open('cfg.cfg', 'r') as f:
                file = f.read()
                print(file)
                if file == b'' or file == '':
                    return ('Файл cfg.cfg пуст', False)
            
            user_id = self.__f.decrypt(file)
            print(f'[INFO] Дешифровка user_id: {user_id}')
            user_id = int(user_id)
            print(user_id)

        except FileNotFoundError:
            print('Нет файла сfg.cfg')
            return ('Нет файла сfg.cfg', False)

        if user_id == '':
            print('[INFO] Файл cfg.cfg пуст')
            return ("Файл cfg.cfg пуст", False)
    
        dt = datetime.datetime.now()
        dt_string = dt.strftime("%d/%m/%Y %H:%M:%S")

        sql = (
            f"SELECT id FROM `avitoreminder`.`user_state` WHERE (`user_id` = '{user_id}')"
        )
        self.__cur.execute(sql)
        res = self.__cur.fetchone()
        
        if res:    
            sql = (
            f'UPDATE `avitoreminder`.`user_state` SET `state`="True", `last_online`="{dt_string}", `last_auth`="{dt_string}" WHERE (`user_id` = "{user_id}"); '
            )
        else:
            sql = (
            f'INSERT INTO `avitoreminder`.`user_state` SET `state`="True", `last_online`="{dt_string}", `last_auth`="{dt_string}", `user_id`="{user_id}"; '
            )
        self.__cur.execute(sql)
        self.__connection.commit()
        print('Данные о состоянии успешно обновлены')

    def get_user_state(self) -> str: # Чтение состояния авторизации #
        """
            Получаем состояние авторизации пользователя
        """
        try:
            with open('cfg.cfg', 'rb') as f:
                file = f.read()
                print(file, type(file))
            
            if file == b'':
                return ('Файл cfg.cfg пуст', False)

            user_id = self.__f.decrypt(file)
            print(f'[INFO] Дешифровка user_id: {user_id}')
            user_id = int(user_id)
            print(user_id, type(user_id))
        
        except FileNotFoundError:
            print('Нет файла сfg.cfg')
            return ('Нет файла сfg.cfg', False)

        sql = (
            f"SELECT `state` FROM `avitoreminder`.`user_state` WHERE (`user_id` = '{user_id}')"
        )
        self.__cur.execute(sql)
        res = self.__cur.fetchone()     

        return res   

    def create_start_code(self) -> str: # Создание старт кода для бота #

        def gen_code():    
            length = 8
            letters = string.ascii_lowercase
            return ''.join(choice(letters) for i in range(length))
        code = gen_code()
        
        def db_req(code):
            sql = (
                f'SELECT * FROM `avitoreminder`.`users` WHERE bot_key = "{code}";'
            )
            self.__cur.execute(sql)
            return self.__cur.fetchall()
        res = db_req(code)

        print(res)
        if res:
            DataBase.create_start_code()

        return code
    
    def get_start_code(self, id: int) -> str: # Получаем старт код из бд # 

        sql = (
            f'SELECT bot_key FROM `avitoreminder`.`users` WHERE id = {id};'
        )
        self.__cur.execute(sql)
        res = self.__cur.fetchone()['bot_key']
        return res