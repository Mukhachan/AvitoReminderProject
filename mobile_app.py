from kivymd.app import MDApp 
from kivymd.uix.label import MDLabel 
from kivy.core.window import Window

#from config import host, user, password, db_name, bot_api_token
from db_connect import db_connect
from DataBase import DataBase
import asyncio
import pymysql



class MainApp (MDApp):
    conn = db_connect()
    
    def build (self): #функция вывода интерфейса

        self.icon = "Static/Лого1.png"
        self.title = "Парсер Авито"
        return MDLabel (text="Текст", halign="center")

if __name__=='__main__':
    
    loop = asyncio.get_event_loop()
    app = MainApp (title="Парсер Авито") 
    loop = asyncio.create_task(app.run())