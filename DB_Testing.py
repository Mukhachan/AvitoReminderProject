from config import db_connect_old
# Подключаемся к бд и получаем экземпляр класса DataBase в лице "conn" #

while True:
    conn = db_connect_old()
    print('\n', conn)
    print("\n[INFO] Выберите функцию для проверки\n")
    print("(1). create_table(self) -> bool\n",
          "(2). db_close(self) -> bool\n",
          "(3). create_user(self, email: str, password: str) -> bool\n",
          "(4). get_user(self, email: str, password: str) -> tuple\n",
          "(5). parsing_data_add(self, user_id: int, link: str, title: str, price: int) -> list\n",
          "(6). parsing_data_read(self) -> list\n",
          "(7). set_request(self, user_id: int, title: str, price_from: int | None, \n",
          "         price_up_to: int | None, add_description: str | None, \n",
          "         city: str, delivery: int, exception: str | None ) -> tuple:\n",
          "(8). get_requests(self) -> list\n",
          "(9). set_user_state(self) -> tuple\n",
          "(10). get_user_state(self) -> str\n",
          "(11). create_start_code(self, id: int) -> str:\n",
          "(12). get_bot_key(self, id: int) -> str:\n",
          "(13). get_userid_by_bot_key(self, bot_key: str) -> int\n",
          "(14). set_bot_key(self, bot_key: str, tg_id: str) -> int\n",
          "(15). update_parsing_state(self, user_id, state)\n",
          "(16). del_request_with_id(self, request_id: int) -> tuple\n",
          "(17). get_request_by_userID(self, user_id: int) -> list\n",
          "(18). update_request_with_id(self, id: int, title: str | None, price_from: int | None,\n",
          "         price_up_to: int | None, city: str | None, add_description: str | None,\n",
          "         delivery: int | None, exception: str | None) -> tuple\n"
          )
    x = input('Цыферка: ')

    if x == '1': # create_table #
        print(conn.create_table())
    elif x == '2': # db_close #
        print(conn.db_close())
        quit()
    elif x == '3': # create_user #
        email = input('Введите email: ')
        password = input('Введите пароль: ')
        print(conn.create_user(email, password))
    elif x == '4': # get_user #
        email = input('Введите email: ')
        password = input('Введите пароль: ')     
   
        print(conn.get_user(email, password))
    elif x == '5': # parsing_data_add #
        user_id = input("Введите ID юзера: ")
        link = input('Введите ссылку: ')
        title = input('Введите название: ')
        price = input('Введите цену: ')
        state = input('Состояние: ')
 
        print(conn.parsing_data_add(user_id, link, title, price, state))
    elif x == '6': # parsing_data_read #
        print(conn.parsing_data_read())        
    elif x == '7': # set_request #
        user_id = int(input('user_id: '))
        title = input('Название: ')
        price_from = int(input('Цена от: '))
        price_up_to = int(input('Цена до: '))
        add_description = input('Добавить в описание: ')
        city = input('Город: ')
        delivery = int(input('Доставка: '))
        exception = input('Исключить из описания: ')
        conn.set_request(user_id, title, price_from, price_up_to, add_description, city, delivery, exception)
    elif x == '8': # get_requests #
        print(conn.get_requests())
    elif x == '9': # set_user_state #
        print(conn.set_user_state())
    elif x == '10': # get_user_state #
        print(conn.get_user_state())
    elif x == '11': # create_start_code #
        print(conn.create_start_code())
    elif x == '12': # get_bot_key #
        id = int(input())
        print(conn.get_bot_key(id))
    elif x == '13': # get_userid_by_bot_key #
        bot_key = input('bot_key: ')
        print(conn.get_userid_by_bot_key(bot_key))
    elif x == '14': # set_bot_key #
        bot_key = input('bot_key: ')
        tg_id = input('tg_id: ')
        print(conn.set_bot_key(bot_key, tg_id))
    elif x == '15': # update_parsing_state # 
        id = int(input())
        state = input()
        conn.update_parsing_state(id, state)
    elif x == '16': # del_request_with_id #
        conn.del_request_with_id(input('Введи id реквеста: '))
    elif x == '17': # get_request_by_userID #
        print(conn.get_request_by_userID(input('Введи user_id: ')))
    elif x == '18': # update_request_with_id #
        id = int(input('id: '))
        title = input('Название: ')
        title = None if title == '' else title
        price_from = input('Цена от: ')
        price_from = None if price_from == '' else int(price_from)
        price_up_to = input('Цена до: ')
        price_up_to = None if price_up_to == '' else int(price_up_to)
        city = input('Город: ')
        city = None if city == '' else city
        add_description = input('Добавить в описание: ')
        add_description = None if add_description == '' else add_description
        delivery = input('Доставка: ')
        delivery = None if delivery == '' else delivery 
        exception = input('Исключить: ')
        exception = None if exception == '' else exception

        print(conn.update_request_with_id(id, title=title, price_from=price_from,
                                          price_up_to=price_up_to, city=city, add_description=add_description,
                                          delivery=delivery,exception=exception
                                          ))
        
    del conn