from kivy.core.window import Window
from kivy. app import App
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget
from kivy.uix.button import Button
from kivy.uix.screenmanager import ScreenManager, Screen
from config import host, user, password, db_name, bot_api_token, db_connect_old
import asyncio

Window.size = (405, 720)
Window.clearcolor = (255/255, 255/255, 255/255)


class LoginScreen(Screen):
    def __init__(self):
        super().__init__()
        self.name = 'LoginScreen'
        self.manager.current = 'LoginScreen'
    def log_in(self, login, password):
        print("Логин: "+ login)
        print("Пароль: "+ password)
        conn.get_user(login, password)
        return RegistrationScreen().to_reg_screen()

class RegistrationScreen(Screen):
    def __init__(self):
        super().__init__()
        self.name = 'RegistrationScreen'
    def to_reg_screen(self):
        self.manager.current = "RegistrationScreen"

class MainApp(App):
    def build(self):
        self.title = "Парсер Авито"
        self.icon = "Static\Лого.png"
        sm = ScreenManager()
        sm.add_widget(LoginScreen())
        sm.add_widget(RegistrationScreen())
        return sm

if __name__=='__main__':
    conn = db_connect_old()
    loop = asyncio.get_event_loop()
    app = MainApp(title="Парсер Авито") 
    loop = asyncio.create_task(app.run())
