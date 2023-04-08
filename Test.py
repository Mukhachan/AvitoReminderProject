from cryptography.fernet import Fernet

"""__key = b'mAJ_0ZIV4Y8FFVx5b-bfBpTNWsqv1hsxt-H5gHvXEYM='
__f = Fernet(__key)
id = input()
print(id)


    # Сохраняем зашифрованый ID в файл #
with open('cfg.cfg', 'wb') as file:
    file.write(__f.encrypt(id.encode()))
    
with open('cfg.cfg', 'rb') as file:    
    f = file.read()
    print(f)
    f = __f.decrypt(f)

f = int(f)
print(f)"""

requests = [{'id': 1, 'user_id': 8, 'link': 'https://www.avito.ru/moskva/telefony/iphone_13_128gb_zelenyy_2766983402', 'title': 'iPhone 13 128Gb Зеленый', 'price': 54990, 'state': 'added'}, {'id': 2, 'user_id': 1, 'link': 'https://www.avito.ru/moskva/telefony/iphone_11_2883219378', 'title': 'iPhone 11', 'price': 19500, 'state': 'sent'}, {'id': 3, 'user_id': 1, 'link': 'https://www.avito.ru/moskva/kollektsionirovanie/byust_putina_2593174114', 'title': 'Бюст путина', 'price': 650, 'state': 'added'}]

for i, elem in enumerate(requests):
    print(i)
    print(elem)