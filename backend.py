import requests
from bs4 import BeautifulSoup as bs
import pandas as pd
import threading

class AvitoRequest:
    async def __init__(self) -> None:
        pass

    async def parser(request: dict) -> tuple:
        pass
    async def main(cores: int) -> bool:
        print('Парсер запустился')