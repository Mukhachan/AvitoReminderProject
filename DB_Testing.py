from DataBase import DataBase
from config import host, user, password, db_name
import pymysql
import pymysql.cursors

# Подключаемся к бд и получаем экземпляр класса DataBase в лице "conn" #
conn = None
def db_connect():
    try:
        global conn 
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

db_connect()

while True:
    print("\n[INFO] Выберите функцию для проверки\n")
    print("(1). create_table(self) -> bool\n",
          "(2). db_close(self) -> bool\n",
          "(3). create_user(self, email: str, password: str) -> bool\n",
          "(4). get_user(self, email: str, password: str) -> tuple\n",
          "(5). parsing_data_add(self, user_id: int, link: str, title: str, price: int) -> list\n",
          "(6). parsing_data_read(self, id: int) -> list\n",
          "(7). set_user_state(self) -> tuple\n",
          "(8). get_user_state(self) -> str\n",
          )
    x = input('Цыферка: ')

    if x == '1':
        print(conn.create_table())
    elif x == '2':
        print(conn.db_close())
    elif x == '3':
        email = input('Введите email: ')
        password = input('Введите пароль: ')
        print(conn.create_user(email, password))
    elif x == '4':
        #email = input('Введите email: ')
        #password = input('Введите пароль: ')     
        email = "aralmuhamet@gmail.com"
        password = "20ArteM06!"   
        print(conn.get_user(email, password))
    elif x == '5':
        """        user_id = input("Введите ID юзера: ")
        link = input('Введите ссылку: ')
        title = input('Введите название: ')
        price = input('Введите цену: ')"""
        user_id = 8
        link = 'https://www.avito.ru/moskva/telefony/iphone_13_128gb_zelenyy_2766983402'
        title = 'iPhone 13 128Gb Зеленый'
        price = 54990
        print(conn.parsing_data_add(user_id, link, title, price))
    elif x == '6':
        id = input('Введите id: ')
        print(conn.parsing_data_read(id))        
    elif x == '7':
        print(conn.set_user_state())
    elif x == '8':
        print(conn.get_user_state())