from backend import AvitoRequest
import asyncio
from os import system

from db_connect import db_connect

system('cls')

while True:
    tsk = input('Что запустить?: ')
    parser = AvitoRequest()
    if tsk == 'main':
        parser.main()
    elif tsk == 'links':
        requests = db_connect().get_requests()
        parser.create_links(requests=requests)
    input("Продолжить?")