from transliterate import translit
import json
import requests
import threading
import math


from selectolax.parser import HTMLParser
from urllib.parse import unquote
from random import randint

import collections.abc
collections.Iterable = collections.abc.Iterable
collections.Mapping = collections.abc.Mapping
collections.MutableSet = collections.abc.MutableSet
collections.MutableMapping = collections.abc.MutableMapping
from hyper.contrib import HTTP20Adapter

from config import proxies, cookie, cores
from mysql.connector.pooling import MySQLConnectionPool
from DataBase import DataBase

class AvitoRequest:
    def __init__(self, Dbase: DataBase, db_pool: MySQLConnectionPool ):
        self.db = Dbase
        self.pool = db_pool

        self.__session = requests.Session()
        self.url = "https://www.avito.ru/"
        self.lock = threading.Lock()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
            "Accept-Language": "ru",
            "cookie": cookie,
        }
        self.proxies = {
            'https' : proxies[randint(0, len(proxies) - 1)],
            'http' : proxies[randint(0, len(proxies) - 1)]
        }
        print("Сейчас используем ip: ", self.proxies['https'])


    def split_list(self, raw_links: list):
        n = math.ceil(len(raw_links) / cores)

        for x in range(0, len(raw_links), n):
            e_c = raw_links[x : n + x]

            if len(e_c) < n:
                e_c = e_c + [None for y in range(n - len(e_c))]
            yield e_c


    def main(self) -> bool:
        """
            Это мэйн функция которая вызывается ботом. Она запускает функцию генерации ссылок
            и соответственно сам парсер
            Она принимает параметр cores который определяет количество потоков для работы парсера.
                Пока что парсер однопоточный
        """
        print('Количество потоков:', cores)
        print('Парсер запустился')
        connection = self.pool.get_connection()
        cursor = connection.cursor(dictionary = True)
        requests = self.db(connection, cursor).get_requests()
        cursor.close()
        connection.close()

        raw_links = self.create_links(requests=requests) # Получаем голый список ссылок #
        links = list(self.split_list(raw_links=raw_links)) # Разбиваем список на cores частей
        threads = []        
        # Создаём cores потоков #
        for i in range(cores): 
            print(i)
            # создаём поток и вызываем start_parser, передаём туда i-тый список  #
            thd = threading.Thread(target=self.start_parser, args=(links[i],))
            thd.start()
            threads.append(thd)
            # Запускаем поток # 
            print(threading.current_thread())

        for t in threads:
            t.join()
        cursor.close()
        connection.close()
        return


    def start_parser(self, links: list): # Вызываем сам парсер и передаём туда i-тую ссылку из списка links #
        connection = self.pool.get_connection()
        cursor = connection.cursor(dictionary = True)
        for i in links:
            with self.lock:    
                if i == None:
                    print('None, скипаю')
                    continue
                user_id = i[0] 
                url = i[1]
                request_id = i[2]
                print(user_id, url, sep='\n')
                threading.current_thread()
                self.parser(
                    request_id=request_id, url=url, user_id=user_id, connection=connection, cursor=cursor
                )



    def parser(self, request_id: int, url: str, user_id: int, connection, cursor) -> tuple:
        self.__session.mount('https://', HTTP20Adapter()) # Позволяет обойти защиту Авито #
        r = self.__session.get(url, data=self.headers, proxies=self.proxies) # Получаем страницу #
        print('status_code:', r.status_code) # Выводим статус код. Если 200, то всё отлично #
        print('Сейчас работает', threading.current_thread())
        raw_page = r.text # Забираем весь текст из страницы #
        
        tree = HTMLParser(raw_page)
        scripts = tree.css('script') # Сохраняем скрипты #
        for script in scripts[::-1]: # Ищем нужный скрипт в котором храняться товары. С конца что бы время сэкономить#
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
        
        parsing_data = self.db(connection, cursor).parsing_data_read()  # считываем всю информацию из таблицы что бы фильтровать товары #
        parsing_data = str(parsing_data)

        
        for key in data:  # Перебираем JSON файл и ищем single-page. В ней храняться данные о товарах #
            if 'single-page' in key:
                for item in data[key]["data"]["catalog"]["items"]: # берём информацию о конкретном товаре по порядку #
                    examination = (
                    f"'user_id': {user_id}, 'request_id': {request_id}, 'link': 'https://www.avito.ru{item['urlPath']}'"
                                )
                    
                    if examination in parsing_data: # Проверяем. Есть ли уже этот товар в БД #
                        print(f'[INFO]. Данный товар уже сохранён в БД {item["id"]} {item["title"]}')
                        continue
                    else:
                        full_url = self.url[:-1] + item["urlPath"] # Собираем большую ссылку #
                        price = item["priceDetailed"]['value'] # Берём цену #
                        self.db(connection, cursor).parsing_data_add(
                            user_id=user_id, request_id = request_id, link=full_url, 
                            title=item["title"], price=price, state='added')
                        
                
    def create_links(self, requests: list) -> list:
        """
            Эта функция генерирует список ссылок(без пагинации) которые надо распарсить возвращает его
        """
        links = []
        print(requests)
        for i, el in enumerate(requests):
            city = translit(el["city"].lower(), 'ru', reversed=True)
            title = el['title']
            user_id = el["user_id"] 
            request_id = el["id"]
            url = f'{self.url}{city}?q={title}'
            print(i, url, request_id)

            links.append((user_id, url, request_id))
        
        return links