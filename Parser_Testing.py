from backend import AvitoRequest
import asyncio

parser = AvitoRequest()
while True:
    tsk = input('Что запустить?: ')
    if tsk == '3':
        parser.main(cores = 1)