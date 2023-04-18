from kivy.core.window import Window
from kivy. app import App
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.graphics import Ellipse
from kivy.metrics import dp
from config import host, user, password, db_name, bot_api_token, db_connect

import asyncio

Window.size = (405, 720)
Window.clearcolor = (255/255, 255/255, 255/255)

class LoginScreen(BoxLayout):
    pass

'''class RoundedButton(Button):
    def __init__(self, **kwargs):
        super(RoundedButton, self).__init__(**kwargs)
        
        # Создание объекта Ellipse для фона кнопки
        with self.canvas.before:
            self.background = Ellipse(pos=self.pos, size=self.size)
        
        # Обновление объекта Ellipse при изменении размеров кнопки
        self.bind(pos=self._update_background, size=self._update_background)
    
    def _update_background(self, instance, value):
        # Обновление объекта Ellipse
        self.background.pos = instance.pos
        self.background.size = instance.size'''

class MainApp(App):
    def build(self):
        self.title = "Парсер Авито"
        self.icon = "Static\Лого.png"
        login_screen = LoginScreen()
        #return Builder.load_file("main.kv")
        return login_screen
    
    def press_button(self, instance):
        print('кнопка "Войти" нажата')
        print(instance)

if __name__=='__main__':
    loop = asyncio.get_event_loop()
    app = MainApp(title="Парсер Авито") 
    loop = asyncio.create_task(app.run())
