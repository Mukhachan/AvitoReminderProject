import requests
from selectolax.parser import HTMLParser
from urllib.parse import unquote
import json
from random import randint
import collections.abc

collections.Iterable = collections.abc.Iterable
collections.Mapping = collections.abc.Mapping
collections.MutableSet = collections.abc.MutableSet
collections.MutableMapping = collections.abc.MutableMapping
from hyper.contrib import HTTP20Adapter

from transliterate import translit

from DataBase import DataBase
from db_connect import db_connect
from config import proxies

class AvitoRequest:
    def __init__(self):
        self.__conn = db_connect()
        print('Парсер подключился к бд:', self.__conn)
        self.__session = requests.Session()
        self.url = "https://www.avito.ru/"

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
            "Accept-Language": "ru"
        }
        self.proxies = {
            'https' : randint(0, len(proxies) - 1)
        }

 
        

    def main(self, cores = 1) -> bool:
        """
            Это мэйн функция которая вызывается ботом. Она запускает функцию генерации ссылок
            и соответственно сам парсер
            Она принимает параметр cores который определяет количество потоков для работы парсера.
                Пока что парсер однопоточный
        """
        print('Парсер запустился')

        requests = self.__conn.get_requests()
        links = AvitoRequest.create_links(self, requests=requests)
        for i in links:
            user_id = i[0] 
            url = i[1]
            request_id = i[2]
            print(user_id, url, sep='\n')
            
            AvitoRequest.parser(self, request_id=request_id, url=url, user_id=user_id)
             # Пока что обрабатываем только первую ссылку #
            

    def parser(self, request_id: int, url: str, user_id: int) -> tuple:
        self.__session.mount('https://', HTTP20Adapter()) # Позволяет обойти защиту Авито #
        r = self.__session.get(url, data=self.headers, proxies=self.proxies) # Получаем страницу #
        print('status_code:', r.status_code) # Выводим статус код. Если 200, то всё отлично #

        raw_page = r.text # Забираем весь текст из страницы #
        
        tree = HTMLParser(raw_page)
        scripts = tree.css('script') # Сохраняем скрипты #
        for script in scripts[::-1]: # Ищем нужный скрипт в котором храняться товары. С конца #
            if "window.__initialData__" in script.text(): 
                raw = script.text().split(';')[0].split('=')[-1].strip() # Чистим JSON от лишнего #
                raw = unquote(raw)
                raw = raw[1:-1]
                data = json.loads(raw) # Преобразуем страницу в формат JSON # 
                
                """
                with open('data.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False)
                    print('Файл JSON сохранён')
                """
                break # Выходим из цикла так как нашли нужный скрипт #
        
        parsing_data = self.__conn.parsing_data_read()  # считываем всю информацию из таблицы что бы фильтровать товары #
        parsing_data = str(parsing_data)
        print(type(parsing_data))
        
        for key in data:  # Перебираем JSON файл и ищем single-page. В ней храняться данные о товарах #

            if 'single-page' in key:
                for item in data[key]["data"]["catalog"]["items"]: # берём информацию о конкретном товаре по порядку #
                    examination = (
                        f"'user_id': {user_id}, 'request_id': {request_id}, 'link': 'https://www.avito.ru{item['urlPath']}'")
                    
                    if examination in parsing_data: # Проверяем. Есть ли уже этот товар в БД #
                        print(f'[INFO]. Данный товар уже сохранён в БД {item["id"]}')
                        continue
                    else:
                        full_url = self.url[:-1] + item["urlPath"] # Собираем большую ссылку #
                        price = item["priceDetailed"]['value'] # Берём цену #
                        self.__conn.parsing_data_add(
                            user_id=user_id, request_id = request_id, link=full_url, 
                            title=item["title"], price=price, state='added')
                        
                
    def create_links(self, requests: list) -> list:
        """
            Эта функция генерирует список ссылок(без пагинации) которые надо распарсить возвращает его
        """
        links = []
        
        for i, el in enumerate(requests):
            city = translit(el["city"].lower(), 'ru', reversed=True)
            title = el['title']
            user_id = el["user_id"] 
            request_id = el["id"]
            url = f'{self.url}{city}?q={title}'
            print(i, url, request_id)

            links.append((user_id, url, request_id))
        
        return links