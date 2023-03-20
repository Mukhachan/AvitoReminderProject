from tkinter import * 
from time import sleep
import sys

root = Tk() 

root.title('AvitoReminder')
root.resizable(False,False)
root.geometry('600x450+750+250')

def close(event):
    sleep(0.15)
    sys.exit()

def add_item(event):
    addWindow = Toplevel(root)
    addWindow.title('Добавить товар')
    addWindow.geometry('500x350')

    TitleLabel = Label(addWindow, text='Название товара')
    TitleLabel.place(relx=0.25,  rely=0.3 )
    TitleEntry = Entry(addWindow, justify=CENTER, width=25)
    TitleEntry.place(relx=0.25, rely=0.4)
    addEntry = Entry(addWindow, justify=CENTER)
    addEntry.place(relx=0.25, rely=0.5)
    exceptionEntry = Entry(addWindow, justify=CENTER)
    exceptionEntry.place(relx=0.5, rely=0.5)

def profile(event):
    addWindow = Toplevel(root)
    addWindow.title('Профиль')
    addWindow.geometry('500x350')

    
    linkBTN = Button(addWindow, text='Подключить телеграмм бота', width='40', height='1')
    linkBTN.place(relx=0.25, rely=0.5)

profile = Button(root, text='Профиль', width=8, height=1)
profile.place(relx=0.93, rely=0.05, anchor=CENTER)

addButton = Button(root, text='Добавить товар', width=16, height=1)
addButton.place(relx=0.11, rely=0.05, anchor=CENTER)

quitButton = Button(root, text='Выйти', width=7, height=1)
quitButton.place(relx=0.93, rely=0.95, anchor=CENTER)




# Логика для кнопок #
quitButton.bind('<Button-1>', close)
addButton.bind('<Button-1>', add_item)

root.mainloop() 