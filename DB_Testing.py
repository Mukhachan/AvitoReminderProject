from DataBase import DataBase
from config import host, user, password, db_name
import pymysql
import pymysql.cursors

# Подключаемся к бд и получаем экземпляр класса DataBase в лице "conn" #
def db_connect():
    try:
        
        db = pymysql.connect(
            host = host,
            port = 3306,
            user = user,
            password = password,
            database = db_name,
            cursorclass = pymysql.cursors.DictCursor
        )
        conn = DataBase(db)
        print(conn)
    except Exception as ex:
        print("[INFO] Ошибка при работе с MySQL: ", ex)
    return conn
conn = db_connect()

while True:
    print("\n[INFO] Выберите функцию для проверки\n")
    print("(1). create_table(self) -> bool\n",
          "(2). db_close(self) -> bool\n",
          "(3). create_user(self, email: str, password: str) -> bool\n",
          "(4). get_user(self, email: str, password: str) -> tuple\n",
          "(5). parsing_data_add(self, user_id: int, link: str, title: str, price: int) -> list\n",
          "(6). parsing_data_read(self, id: int) -> list\n",
          "(7). set_request(self, user_id: int, title: str, price: int | None, \nadd_description: str | None, exception: str | None) -> tuple\n",
          "(8). get_requests(self) -> list\n",
          "(9). set_user_state(self) -> tuple\n",
          "(10). get_user_state(self) -> str\n",
          "(11). create_start_code(self, id: int) -> str:\n",
          "(12). get_start_code(self, id: int) -> str:\n",
          "(13). get_userid_set_bot_key(self, bot_key: str, tg_id: str) -> int\n"
          )
    x = input('Цыферка: ')

    if x == '1': # create_table #
        print(conn.create_table())
    elif x == '2': # db_close #
        print(conn.db_close())
        quit()
    elif x == '3': # create_user #
        email = input('Введите email: ')
        password = input('Введите пароль: ')
        print(conn.create_user(email, password))
    elif x == '4': # get_user #
        email = input('Введите email: ')
        password = input('Введите пароль: ')     
   
        print(conn.get_user(email, password))
    elif x == '5': # parsing_data_add #
        """        user_id = input("Введите ID юзера: ")
        link = input('Введите ссылку: ')
        title = input('Введите название: ')
        price = input('Введите цену: ')"""
        user_id = 8
        link = 'https://www.avito.ru/moskva/telefony/iphone_13_128gb_zelenyy_2766983402'
        title = 'iPhone 13 128Gb Зеленый'
        price = 54990
        print(conn.parsing_data_add(user_id, link, title, price))
    elif x == '6': # parsing_data_read #
        id = input('Введите id: ')
        print(conn.parsing_data_read(id))        
    elif x == '7': # set_request #
        user_id = int(input('узер иди: '))
        title = input('Название: ')
        price = int(input('Цена: '))
        add_description = input('Добавить в описание: ')
        exception = input('Исключить из описания: ')
        conn.set_request(user_id, title, price, add_description, exception)
    elif x == '8':
        print(conn.get_requests())
    elif x == '9': # set_user_state #
        print(conn.set_user_state())
    elif x == '10': # get_user_state #
        print(conn.get_user_state())
    elif x == '11': # create_start_code #
        print(conn.create_start_code())
    elif x == '12': # get_start_code #
        id = int(input())
        print(conn.get_start_code(id))
    elif x == '13': # get_userid_set_bot_key #
        bot_key = input('bot_key: ')
        tg_id = input('tg_id: ')
        print(conn.get_userid_set_bot_key(bot_key, tg_id))