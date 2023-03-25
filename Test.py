from cryptography.fernet import Fernet

__key = b'mAJ_0ZIV4Y8FFVx5b-bfBpTNWsqv1hsxt-H5gHvXEYM='
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
print(f)