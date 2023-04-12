from cryptography.fernet import Fernet
import base64
"""__key = b'mAJ_0ZIV4Y8FFVx5b-bfBpTNWsqv1hsxt-H5gHvXEYM='
__f = Fernet(__key)
id = input()
print(id)


    # Сохраняем зашифрованый ID в файл #
with open('cfg.cfg', 'wb') as file:
    file.write(__f.encrypt(id.encode()))
    
with open('cfg.cfg', 'rb') as file:    
    f = file.read()
    print(f)
    f = __f.decrypt(f)

f = int(f)
print(f)"""
"""
requests = [{'id': 1, 'user_id': 8, 'link': 'https://www.avito.ru/moskva/telefony/iphone_13_128gb_zelenyy_2766983402', 'title': 'iPhone 13 128Gb Зеленый', 'price': 54990, 'state': 'added'}, 
{'id': 2, 'user_id': 1, 'link': 'https://www.avito.ru/moskva/telefony/iphone_11_2883219378', 'title': 'iPhone 11', 'price': 19500, 'state': 'sent'}, {'id': 3, 'user_id': 1, 'link': 'https://www.avito.ru/moskva/kollektsionirovanie/byust_putina_2593174114', 'title': 'Бюст путина', 'price': 650, 'state': 'added'}]

for i, elem in enumerate(requests):
    print(i)
    print(elem)"""
"""
p_from = input().encode('utf-8')
p_to = input().encode('utf-8')

x = b'\x01(\x02\x02\x01\x02\x01E\xc6\x9a\x0c\x1b{"from":' + p_from + b',"to":' + p_to +  b'}'
z = x
x = base64.b64encode(x)
print(x)

x = base64.b64decode(x)

print(x)
print(z == x)"""


import requests
from bs4 import BeautifulSoup

class AvitoParser:
    def __init__(self, city, query, min_price=None, max_price=None, with_delivery=False):
        self.city = city
        self.query = query
        self.min_price = min_price
        self.max_price = max_price
        self.with_delivery = with_delivery
        self.base_url = "https://www.avito.ru"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    def search_items(self):
        query_url = f"{self.base_url}/{self.city}?q={self.query}"
        if self.min_price:
            query_url += f"&pmin={self.min_price}"
        if self.max_price:
            query_url += f"&pmax={self.max_price}"
        if self.with_delivery:
            query_url += "&f=550_905b"

        response = requests.get(query_url, headers=self.headers)
        soup = BeautifulSoup(response.content, 'html.parser')

        item_containers = soup.find_all('div', class_='item_table-wrapper')
        for container in item_containers:
            title_element = container.find('h3', class_='snippet-title')
            title = title_element.text.strip()
            price_element = container.find('span', class_='snippet-price')
            price = price_element.text.strip()
            link_element = container.find('a', class_='snippet-link')
            link = f"{self.base_url}{link_element['href']}"

            print("Title:", title)
            print("Price:", price)
            print("Link:", link)
            print("-----")

# Пример использования парсера
parser = AvitoParser(city="moskva", query="iphone", min_price=10000, max_price=50000, with_delivery=1)
parser.search_items()
