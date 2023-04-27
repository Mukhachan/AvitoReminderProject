from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
from random import choice
from config import crypt_key, user_online, old_records
import string
import datetime
import pymysql

class DataBase:
    def __init__(self, connection = None, cursor = None): # Инициализация глобальных переменных # 
        self.__connection = connection
        self.__cur = cursor

        self.__key = crypt_key # Ключ для шифровки файла cfg #
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
        
        if ex:
            print(ex)
            print('Такой пользователь уже зарегистрирован')
            return False
        
        try:
             # Создаём запись в таблице users #
            code = self.create_start_code()
            
            sql = (
            f'INSERT INTO `avitoreminder`.`users` (email, password, bot_key) VALUES ("{email}", "{password}", "{code}")'
            )
             
            self.__cur.execute(sql)
            self.__connection.commit()
            print('Успешная регистрация')
             # Берём ID юзера #
            sql = (
                f'SELECT id from `avitoreminder`.`users` WHERE email = "{email}"'
            )
            self.__cur.execute(sql)
            
            id = str(self.__cur.fetchone()['id'])

             # Сохраняем зашифрованый ID в файл #
            with open('cfg.cfg', 'wb') as file:
                file.write(self.__f.encrypt(id.encode()))
            self.set_user_state(id)
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

        if check_password_hash(hash_psw, password):
            self.set_user_state(id)
            print('Успешная авторизация')
            bot_key = self.get_bot_key(id=id)
            if bot_key[0] == 'chat_id':
                print('(get_user) тг привязан')
                return ("Успешная авторизация", True, id, True)
            elif bot_key[0] == 'start_code':
                print('(get_user) тг НЕ привязан')
                return ("Успешная авторизация", True, id, bot_key)
        else:
            print("Неверный пароль")
            return("Неверный пароль", False)

    def parsing_data_add(self, user_id: int, request_id: int, link: str, title: str, price: int, state: str) -> None: # Добавление в parsing data #
        """ 
        Функция используется для добавления данных в таблицу parsing_data, после парсинга Авито
        """
    
        try:
            current_time = datetime.datetime.now()
            
            title = title.replace('"', '')
            title = title.replace('”', '')
            title = title.replace('`', '')

            sql = f'INSERT INTO `avitoreminder`.`parsing_data` VALUES (NULL, {user_id}, {request_id}, "{link}", "{title}", "{price}", "{state}", "{current_time}")'
            
            self.__cur.execute(sql)
            self.__connection.commit()
            print("[INFO]. Товар добавлен", title)
        except pymysql.err.InterfaceError:
            pass
        
        except Exception as e:
            print('[INFO] Возникла ошибка при добавлении данных в таблицу parsing_data: ', e)
            print(sql)
 
    def parsing_data_read(self) -> list: # Чтение из parsing_data #
        """
            Собираем все данные с таблицы parsing_data
            Возвращает список из словарей
        """
        try:
            self.__cur.execute(f"SELECT * FROM `avitoreminder`.`parsing_data`")
            res = self.__cur.fetchall()
            
            return res if res else 'Список пуст'
        
        except Exception as e:
            print('Ошибка при чтении БД (parsing_data)', e)

    def parsing_data_del_time(self) -> bool:
        """
            Эта функция удаляет записи которые были созданы и показаны более 7 дней назад
        """
        current_time = datetime.datetime.now()
        delete_time = current_time - datetime.timedelta(days=old_records)          
        try: # Удаляем из БД#
            self.__cur.execute(f"DELETE FROM `avitoreminder`.`parsing_data` WHERE `state`='sent' AND `state_date`< '{delete_time}'")
            self.__connection.commit()

            print('\nУдалили много записей которые были созданы более 7 дней назад')
            return True
        
        except Exception as e:
            print('При удалении возникла ошибка: ', e)
            return False

    def del_parsing_data_without_requests(self, pd_len_after: int = 0 ) -> bool:
        """
            Эта функция удаляет данные за которыми не следят
        """

        parsing_data = self.parsing_data_read()
        if len(parsing_data) == 0:
            print('Таблица parsing_data пуста')
            return False
        
        for i in parsing_data:
            x = self.get_request(i['request_id'])
            if x == 'Список пуст':
                print(i['request_id'], "Удаляю")
                try:
                    self.__cur.execute(
                        f'DELETE FROM `avitoreminder`.`parsing_data` WHERE `request_id` = {i["request_id"]}'
                    )
                    self.__connection.commit()

                except Exception as e:
                    print('Появилась непонятная ошибка', e)
                    return False
            if x != 'Список пуст':
                print(i['request_id'], 'удалять не будем')
        pd_len_after = len(parsing_data) - len(self.parsing_data_read())

        print('Из parsing_data удалено ненужных товаров:', pd_len_after, '\n')
        return True if pd_len_after != 0 else False

    def set_request(self, user_id: int, title: str, price_from: int | None, 
                    price_up_to: int | None, add_description: str | None, 
                    city: str, delivery: int, exception: str | None ) -> tuple: # Добавление запроса для Авито #
        """
            Добавляем в таблицу requests данные для парсинга
        """
        try:
            self.__cur.execute(
                f'INSERT INTO `avitoreminder`.`requests` VALUES (NULL, {user_id}, "{title}", {price_from}, {price_up_to}, "{add_description}", "{city}", {delivery},"{exception}")'
            )
            self.__connection.commit()
            print("[INFO] Запрос успешно создан")
        except Exception as e:
            print('Возникла ошибка при добавлении')
            print(e)

    def get_requests(self) -> list: # Список запросов для авито #
        """
            Возвращает огромный список из словарей с запросами для Авито
        """
        try:
            self.__cur.execute(
                f'SELECT * FROM `avitoreminder`.`requests`'
            )
            res = self.__cur.fetchall()
            return res if res else None
        except:
            print('Ошибка при чтении БД (requests)')

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
                if file == b'' or file == '':
                    return ('Файл cfg.cfg пуст', False)
            
            user_id = self.__f.decrypt(file)
            print(f'[INFO] Дешифровка user_id: {user_id}')
            user_id = int(user_id)


        except FileNotFoundError:
            print('Нет файла сfg.cfg')
            return ('Нет файла сfg.cfg', False)

        if user_id == '':
            print('[INFO] Файл cfg.cfg пуст')
            return ("Файл cfg.cfg пуст", False)
    
        dt = datetime.datetime.now()
        dt_string = dt.strftime("%d/%m/%Y")

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

    def get_user_state(self) -> tuple: # Чтение состояния авторизации #
        """
            Получаем состояние авторизации пользователя
        """
        try:
            with open('cfg.cfg', 'rb') as f:
                file = f.read()
                
            
            if file == b'':
                return ('Файл cfg.cfg пуст', False)

            user_id = self.__f.decrypt(file)
            print(f'[INFO] Дешифровка user_id: {user_id}')
            user_id = int(user_id)
            
        
        except FileNotFoundError:
            print('Нет файла сfg.cfg')
            return ('Файла cfg.cfg нет', False)

        sql = (
            f"SELECT `state` FROM `avitoreminder`.`user_state` WHERE (`user_id` = '{user_id}')"
        )
        self.__cur.execute(sql)
        res = self.__cur.fetchone()['state'] 
        if res == "True":
            return ('Пользователь авторизирован', True)
        elif res == "False":
            return ('Пользователь не авторизирован', False)   

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
            self.create_start_code()

        return code
    
    def get_bot_key(self, id: int) -> tuple: # Получаем бот кей из бд # 
        """ Получаем bot_key из бд c помощью ID 
        """
        sql = (
            f'SELECT bot_key FROM `avitoreminder`.`users` WHERE id = {id};'
        )
        self.__cur.execute(sql)
        
        res = self.__cur.fetchone()
        if res:
            res = res['bot_key']
            if str(res).isdigit(): # Если это число то тг уже привязан # 
                print('chat_id :', res)
                return ('chat_id', res)
            
            elif str(res).isdigit() == False: # Если тг не привязан #
                print('start_code:', res)
                return ('start_code', res)

        else:
            return None

    def get_userid_by_bot_key(self, bot_key: str) -> int: # получаем user_id с помощью bot_key #
        """ Берём ID пользователя из записи с нужным на bot_key """

        sql = (
            f'SELECT * FROM `avitoreminder`.`users` WHERE bot_key = "{bot_key}";'
        )
        self.__cur.execute(sql)
        fetch = self.__cur.fetchone()
        if fetch == None:
            print('fetch -', fetch)
            return ('Такой Bot_key не найден в бд', False)
        
        return (fetch["id"], True)

    def set_bot_key(self, bot_key: str, tg_id: str) -> tuple: # сохраняем id чата #
        """
            Получает на вход старткод и ID чата. записывает вместо ячейки bot_key, ID чата в тг
        """

        id = self.get_userid_by_bot_key(bot_key) # Сохраняем ID #

         # Обновляем запись с пользователем и записываем в bot_key id чата в телеграмме #
        sql = (
            f'UPDATE `avitoreminder`.`users` SET `bot_key`= {tg_id} WHERE (`id` = {id[0]});'
        )
        self.__cur.execute(sql)
        self.__connection.commit()

        return (id, True)
    
    def update_parsing_state(self, id: int, state: str) -> tuple:
        """
            Получает на вход id записи в parsing_data и состояние на которое надо изменить
        """
        sql = (
            f'UPDATE `avitoreminder`.`parsing_data` SET `state`="{state}" WHERE (`id` = {id});'
        )
        self.__cur.execute(sql)
        self.__connection.commit()

        return ('Всё поменяли', True)
    
    def get_request(self, id: int) -> dict:
        """
            На вход получает ID реквеста. Если он есть, то возвращает его.
            Если нет то пишет 'Список пуст'
        """
        try:
            sql = (
                f'SELECT * FROM `avitoreminder`.`requests` WHERE id = {id}'
            )
            self.__cur.execute(sql)
            res = self.__cur.fetchone()
            return res if res else 'Список пуст'
        
        except Exception as e:
            print('[INFO]. Возникла ошибка в функции get_request:', e)

    def get_request_by_userID(self, user_id: int) -> list:
        """
            Эта функция возвращает список запросов за которыми следит пользователь.
        """
        try:
            sql = (
                f'SELECT * FROM `avitoreminder`.`requests` WHERE user_id = {user_id}'
            )
            self.__cur.execute(sql)
            res = self.__cur.fetchall()
            print(len(res))
            return res if res else ('Список пуст')
        
        except Exception as e:
            print('Возникла ошибка (get_request_by_userID)', e)
  
    def del_request_with_id(self, request_id: int) -> tuple:
        """
            Эта функция удаляем запрос с переданым ему ID

            Возвращает кортеж вида ('Сообщение', bool)
        """
        try:
            sql = (
                f'DELETE FROM `avitoreminder`.`requests` WHERE id = {request_id} '
            )
            self.__cur.execute(sql)
            self.__connection.commit()
            count = self.__cur.rowcount
            if count == 0:
                print('Такой реквест не найден')
                return ('Такого товара нет. Обновите список', False)
            else:
                print('Товар успешно удалён')
                return ('Товар успешно удалён', True)
        
        except Exception as e :
            print('Возникла ошибка', e)

    def update_request_with_id(self, id: int, title: str | None, price_from: int | None,
                                price_up_to: int | None, city: str | None, add_description: str | None,
                                delivery: int | None, exception: str | None) -> tuple:
        """
            Эта функция принимает все значения которые можно изменить в реквесте. 
            Либо изменяется значение либо, оно None, тогда оно остаётся прежним.
        """
        update_fields = []
        args = ['title', 'price_from', 'price_up_to', 'city', 'add_description', 'delivery', 'exception']
        try:
            for field in args:
                if locals()[field] is not None:
                    update_fields.append(f"{field} = '{locals()[field]}'")

            if not update_fields:
                return ('Ничего изменять не пришлось', False)

            sql = f"UPDATE `avitoreminder`.`requests` SET {', '.join(update_fields)} WHERE id = {id}"

            self.__cur.execute(sql)
            self.__connection.commit()
            return ('Данные успешно обновлены', True)
        
        except Exception as e:
            print('Возникла ошибка (update_request_with_id): ', e)
            return ('При выполнении запроса возникла ошибка', False)

    def check_user_last_online(self) -> tuple:
        """
            Эта функция перебирает всех пользователей в бд и проверяет когда они были последний раз онлайн.
            Если больше 14 дней назад, то мы меняем состояние авторизации на False. 
            Функция должна запускать не чаще чем раз в сутки.
        """
        current_time = datetime.datetime.now()
        delete_time = current_time - datetime.timedelta(days=user_online)          
        try:
            sql = (
            f'UPDATE `avitoreminder`.`user_state` SET `state`= "False" WHERE `last_online`< "{delete_time}"'
            )
            self.__cur.execute(sql)
            self.__connection.commit()

        except Exception as e:
            print('Возникла ошибка (check_user_last_online): ', e)
            return ('Возникла ошибка (check_user_last_online)', False)
        
        return (self.__cur.rowcount, True)
    
    def __del__(self):
        """
            Это диструктор, он чистит память когда удаляется последний экземпляр класса 
        """
        print('Удаляю последний экземпляр DataBase')