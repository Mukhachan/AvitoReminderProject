from backend import AvitoRequest
from DataBase import DataBase
from os import system

from config import db_connect_pool

system('cls')
db_pool = db_connect_pool()

# Создаём пустой экземпляр класса #
DBase = DataBase
# Создаём экземпляр класса AvitoRequest, передаём экземпляр DataBase и пул соединений #

tsk = input('Что запустить?: ')

if tsk == 'main':
    parser = AvitoRequest(DBase, db_pool)
    parser.main()
input("\Парсер отработал. (Enter для выхода)\n")