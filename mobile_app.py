from config import host, user, password, db_name, bot_api_token
from kivymd.app import MDApp 
from kivymd.uix.label import MDLabel 
from DataBase import DataBase
import pymysql

def db_connect():
    try:
        db = pymysql.connect(
            host = host,
            port = 3306,
            user = user,
            password = password,
            database = db_name,
            cursorclass = pymysql.cursors.DictCursor
        )
        conn = DataBase(db)
        
    except Exception as ex:
        print("[INFO] Ошибка при работе с MySQL: ", ex)
    return conn


class MainApp (MDApp):
    def build (self): #функция вывода интерфейса
        self.icon = "Static/Лого1.png"
        self.title = "Парсер Авито"
        return MDLabel (text="Текст", halign="center")

if __name__=='__main__':
    conn = db_connect()
    state = conn.get_user_state()
    app = MainApp (title="Парсер Авито") 
    app.run()