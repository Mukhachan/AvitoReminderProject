from backend import AvitoRequest
from os import system

from config import cores, db_connect

system('cls')

tsk = input('Что запустить?: ')
parser = AvitoRequest()
if tsk == 'main':
    parser.main(cores=cores)
    
elif tsk == 'links':
    requests = db_connect().get_requests()
    parser.create_links(requests=requests)
input("Продолжить?\n")