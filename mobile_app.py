from kivy.core.window import Window
from kivy. app import App
from kivy.lang import Builder
from kivy.metrics import dp
from config import host, user, password, db_name, bot_api_token, db_connect

import asyncio

Window.size = (405, 720)
Window.clearcolor = (255/255, 255/255, 255/255)

class MainApp(App):
    def build(self):
        self.title = "Парсер Авито"
        self.icon = "Static\Лого.png"
        return Builder.load_file("main.kv")
    
    def press_button(self, instance):
        print('кнопка "Войти" нажата')
        print(instance)

if __name__=='__main__':
    loop = asyncio.get_event_loop()
    app = MainApp(title="Парсер Авито") 
    loop = asyncio.create_task(app.run())
