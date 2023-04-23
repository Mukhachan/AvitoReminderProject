from kivy.core.window import Window
from kivy. app import App
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.widget import Widget
from kivy.graphics import Ellipse
from kivy.metrics import dp
from config import host, user, password, db_name, bot_api_token, db_connect_old
import asyncio

Window.size = (405, 720)
Window.clearcolor = (255/255, 255/255, 255/255)


class LoginScreen(BoxLayout):
    def log_in(self, login, password):
        print("Логин: "+ login)
        print("Пароль: "+ password)
        conn.get_user(login, password)

class MainApp(App):
    def build(self):
        self.title = "Парсер Авито"
        self.icon = "Static\Лого.png"
        login_screen = LoginScreen()
        #return Builder.load_file("main.kv")
        return login_screen


if __name__=='__main__':
    conn = db_connect_old()
    loop = asyncio.get_event_loop()
    app = MainApp(title="Парсер Авито") 
    loop = asyncio.create_task(app.run())
