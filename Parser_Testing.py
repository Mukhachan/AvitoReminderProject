from backend import AvitoRequest
from DataBase import DataBase
from os import system

from config import cookie, proxies, cores, db_connect_pool

system('cls')
db_pool = db_connect_pool()

# Создаём пустой экземпляр класса #
DBase = DataBase
# Создаём экземпляр класса AvitoRequest, передаём экземпляр DataBase и пул соединений #
parser = AvitoRequest(DBase, db_pool)

tsk = input('Что запустить?: ')

if tsk == 'main':
    parser.main()

"""
elif tsk == 'links':
    requests = db_connect().get_requests()
    parser.create_links(requests=requests)
input("Продолжить?\n")"""