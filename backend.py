import grequests
import requests

from selenium import webdriver

from transliterate import translit

#from DataBase import DataBase
from db_connect import db_connect


class AvitoRequest:
    def __init__(self):
        self.__conn = db_connect()
        print('Парсер подключился к бд:', self.__conn)

    def main(self, cores: int) -> bool:
        print('Парсер запустился')

        requests = self.__conn.get_requests()
        AvitoRequest.create_links(requests=requests)


    def parser(self, request: dict) -> tuple:
        pass

    def create_links(requests):
        links = []
        browser = webdriver.Firefox()
        

        for i in requests:
            
            city = translit(i["city"].lower(), 'ru', reversed=True)
            title = i['title']
            delivery = i['delivery']
            p_from = i['price_from']
            p_to = i['price_up_to']


            first_link = "https://www.avito.ru/" + city + "?q=" + title
            datas = {
                'q' : title,
                'd' : delivery,
                'p_from' : p_from,
                'p_to': p_to,
            }
            s = requests.Session()

            loging = s.post("https://www.avito.ru/", data = datas)
            print(loging.text)

            #link = f'https://www.avito.ru/{city}?d={delivery}&f={price}&q={title}' 
            #links.append(link)
            #print(link)    
