from transliterate import translit
from transliterate.exceptions import LanguagePackNotFound
import json
import requests
import threading
import math
from time import sleep

from selectolax.parser import HTMLParser
from urllib.parse import unquote
from random import randint

import collections.abc
collections.Iterable = collections.abc.Iterable
collections.Mapping = collections.abc.Mapping
collections.MutableSet = collections.abc.MutableSet
collections.MutableMapping = collections.abc.MutableMapping
from hyper.contrib import HTTP20Adapter
from requests.exceptions import RetryError
from urllib3.util.retry import Retry

from config import proxies, cookie, cores
from mysql.connector.pooling import MySQLConnectionPool
from DataBase import DataBase


class AvitoRequest:
    def __init__(self, Dbase: DataBase, db_pool: MySQLConnectionPool ):
        self.db = Dbase
        self.pool = db_pool

        self.__session = requests.Session()
        self.url = "https://www.avito.ru/"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
            "Accept-Language": "ru",
            "cookie": cookie,
        }
        self.proxies = {
            'https' : proxies[randint(0, len(proxies) - 1)],
            'http' : proxies[randint(0, len(proxies) - 1)]
        }
        self.retry_strategy = Retry(
                                    total=3,
                                    backoff_factor=1,
                                    status_forcelist=[429, 500, 502, 503, 504],
                                    method_whitelist=["GET"],
                                )
        
        print("Сейчас используем ip: ", self.proxies['https'])


    def split_list(self, raw_links):
        part_len = math.ceil(len(raw_links)/cores)
        return [raw_links[part_len*k:part_len*(k+1)] for k in range(cores)]

    def main(self) -> bool:
        try:
            mainthread = threading.Thread(target=self.threads)
            mainthread.start()
            print('Инициализирую основной поток:', threading.current_thread())
            mainthread.join()
        except:
            print('В основном потоке появилась ошибка')
            return False
        return True
                 
    def threads(self) -> bool:
        """
            Это мэйн функция которая вызывается ботом. Она запускает функцию генерации ссылок
            и соответственно сам парсер
            Она принимает параметр cores который определяет количество потоков для работы парсера.

        """
        print('Количество потоков:', cores, end='\n\n')
        print('Парсер запустился')
        connection = self.pool.get_connection()
        cursor = connection.cursor(dictionary = True)
        requests = self.db(connection, cursor).get_requests()
        cursor.close()
        connection.close()

        raw_links = self.create_links(requests=requests) # Получаем голый список ссылок #
        links = list(self.split_list(raw_links=raw_links)) # Разбиваем список на cores частей
        threads = []        
        print('\nСПИСОК ССЫЛОК: ', links)
        # Создаём потоки #
        for i in links: 
            sleep(1)
            # создаём поток и вызываем start_parser, передаём туда i-тый список  #
            if len(i) == 0:
                continue
            thd = threading.Thread(target=self.start_parser, args=(i,))
            thd.start()
            threads.append(thd)
            # Запускаем поток # 
            print('Сейчас обрабатываетcя ссылка', i, 'В треде:', threading.current_thread())
            
        print('\nСПИСОК ПОТОКОВ:', threads, end='\n\n')
    
        for t in threads:
            t.join()
        cursor.close()
        connection.close()
        
        return True


    def start_parser(self, links: list): # Вызываем сам парсер и передаём туда i-тую ссылку из списка links #
        connection = self.pool.get_connection()
        cursor = connection.cursor(dictionary = True)

        for i in links:
            if len(i) == 0:
                print('0, скипаю')
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
        self.__session.mount('https://', HTTP20Adapter(max_retries = self.retry_strategy)) # Позволяет обойти защиту Авито #
        try:
            r = self.__session.get(url=url, data=self.headers, proxies=self.proxies) # Получаем страницу #
            if r.status_code != 200:
                print("Запрос потока", threading.current_thread(), "не сработал и выдал код:", r.status_code)
        except RetryError:
            print("Ошибка после повтора")

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
        
        for i, el in enumerate(requests):
            try:
                city = translit(value=el["city"].lower(), language_code='ru', reversed=True)
                title = el['title']
                user_id = el["user_id"] 
                request_id = el["id"]
                url = f'{self.url}{city}?q={title}'
                print(i, url, request_id)

                links.append((user_id, url, request_id))
            except LanguagePackNotFound:
                print("\nLanguagePackNotFound, но мы постараемся запустить функцию заново\n")
                sleep(1)
                self.create_links(requests)
                break

        return links