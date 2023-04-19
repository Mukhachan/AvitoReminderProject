from config import db_connect_old

print('<--- --->')

ans = input('Авторизоваться или регистрироваться? (1,2): ')
conn = db_connect_old()

if ans == '1':
    print("Авторизация\n")
    while True:
        login = input('Введи логин: ')
        password = input('Введи пароль: ')
        
        print('Пробую авторизоваться\n')
        report = conn.get_user(email=login, password=password)
        
        if report[3] == True:
            print('Телеграм уже привязан')
        else:
            ans = input('Привязать телеграм? (y/n): ')
        
            if ans == 'y':
                print(f'Вот Ваша ссылка: http://t.me/Avito_Parser_1kbot?start={report[3][1]}')
                input('enter')
                break
            
            elif ans == 'n':
                print("Ну всё тогда")
                input('enter')
                break

            else:
                print('Чё ты ввёл..')

elif ans == '2':
    print('Регистрация\n')
    while True:
        login = input('Введи email/логин: ')
        password1 = input('Введи пароль: ')
        password2 = input('Повторно введи пароль: ')
        if password1 == password2:
            print('Регистрирую\n')
            conn.create_user(email=login, password=password1)
            break
        else:
            print('Ты ввёл разные пароли')
            input('enter')