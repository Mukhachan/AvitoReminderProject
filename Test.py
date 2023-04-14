
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
"""
requests = [{'id': 1, 'user_id': 8, 'link': 'https://www.avito.ru/moskva/telefony/iphone_13_128gb_zelenyy_2766983402', 'title': 'iPhone 13 128Gb Зеленый', 'price': 54990, 'state': 'added'}, 
{'id': 2, 'user_id': 1, 'link': 'https://www.avito.ru/moskva/telefony/iphone_11_2883219378', 'title': 'iPhone 11', 'price': 19500, 'state': 'sent'}, {'id': 3, 'user_id': 1, 'link': 'https://www.avito.ru/moskva/kollektsionirovanie/byust_putina_2593174114', 'title': 'Бюст путина', 'price': 650, 'state': 'added'}]

for i, elem in enumerate(requests):
    print(i)
    print(elem)"""
"""
p_from = input().encode('utf-8')
p_to = input().encode('utf-8')

x = b'\x01(\x02\x02\x01\x02\x01E\xc6\x9a\x0c\x1b{"from":' + p_from + b',"to":' + p_to +  b'}'
z = x
x = base64.b64encode(x)
print(x)

x = base64.b64decode(x)

print(x)
print(z == x)"""
"""
data = {'id': 1, 'user_id': 8, 'link': 'https://www.avito.ru/moskva/telefony/iphone_13_128gb_zelenyy_2766983402', 'title': 'iPhone 13 128Gb Зеленый', 'price': 54990, 'state': 'added'}

if 'moskva/telefony/iphone_13_128gb_zelenyy_2766983402' in data['link']:
    print('нашлось')
else:
    print('-')
"""
from _thread import start_new_thread
import numpy as np

#lst = np.random.randint(-10, 30, 50)
lst = [i for i in range(1, 21)]
print(lst)



def function(lst):
    for i in lst:
        print(i)

start_new_thread(function, (lst[:len(lst)//2], ))
start_new_thread(function, (lst[len(lst)//2:], ))