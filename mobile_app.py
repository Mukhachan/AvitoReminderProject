from kivymd.app import MDApp 
from kivymd.uix.label import MDLabel 
class MainApp (MDApp):
    def build (self): #функция вывода интерфейса
        #self.icon = 
        self.title = "Парсер Авито"
        return MDLabel (text="Текст", halign="center")

if __name__=='__main__':
    app = MainApp (title="Парсер Авито") 
    app.run()