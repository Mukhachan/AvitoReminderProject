from tkinter import * 

root = Tk() 

root.title('AvitoReminder')
root.resizable(False,False)
root.geometry('600x450+750+250')

profile = Button(root, text='Профиль', width=8, height=1)
profile.place(relx=0.93, rely=0.05, anchor=CENTER)

addButton = Button(root, text='Добавить товар', width=16, height=1)
addButton.place(relx=0.11, rely=0.05, anchor=CENTER)

quitButton = Button(root, text='Выйти', width=7, height=1)
quitButton.place(relx=0.93, rely=0.95, anchor=CENTER)




# Логика для кнопок #
root.mainloop() 