import requests
from bs4 import BeautifulSoup

import collections.abc
collections.Iterable = collections.abc.Iterable
collections.Mapping = collections.abc.Mapping
collections.MutableSet = collections.abc.MutableSet
collections.MutableMapping = collections.abc.MutableMapping
from hyper.contrib import HTTP20Adapter

from transliterate import translit

#from DataBase import DataBase
from db_connect import db_connect


class AvitoRequest:
    def __init__(self):
        self.__conn = db_connect()
        print('Парсер подключился к бд:', self.__conn)
        self.__session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
            "Accept-Language": "ru"
        }
        self.url = "https://www.avito.ru/"

    def main(self, cores: int) -> bool:
        print('Парсер запустился')

        requests = self.__conn.get_requests()
        links = AvitoRequest.create_links(self, requests=requests)
        for i in links:
            AvitoRequest.parser(self, i)
            break
            


    def parser(self, request: dict) -> tuple:
        self.__session.mount('https://', HTTP20Adapter())
        r = self.__session.get(request, data=self.headers)
        print('status_code:', r.status_code)

        raw_page = r.text

        soup = BeautifulSoup(raw_page, 'lxml')
        
        container = soup.select('div.items-items-kAJAg')
        for item in container:
            title = soup.select('.title-root-zZCwT iva-item-title-py3i_ title-listRedesign-_rejR title-root_maxHeight-X6PsH text-text-LurtD text-size-s-BxGpL text-bold-SinUO')
            print(title)
            

    def create_links(self, requests: list) -> list:
        links = []
        
        for i, el in enumerate(requests):
            city = translit(el["city"].lower(), 'ru', reversed=True)
            title = el['title']

            url = f'{self.url}{city}?q={title}' 
            print(i, url)
            links.append(url)
            
        return links