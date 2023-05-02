host = "45.9.41.88"
user = 'root'
password = 'dRi13iXz#k4pM{v2}b~~?2HYbnl8rJxz'
db_name = 'avitoreminder'
bot_api_token = '6039503049:AAFheifhdgdt20Reb9vCMGR1O60y3cAIgys'

crypt_key = b'mAJ_0ZIV4Y8FFVx5b-bfBpTNWsqv1hsxt-H5gHvXEYM=' # Ключ для шифровки файла cfg
cores = 2
parser_timer = 2700 # 45 минут #
garbage_collector_time = 86400  # 24 часа #
mes_len = 5

user_online = 14
old_records = 7

cookie = '__cfduid=da6b6b5b9f01fd022f219ed53ac3935791610912291; sessid=ef757cc130c5cd228be88e869369c654.1610912291; _ga=GA1.2.559434019.1610912292; _gid=GA1.2.381990959.1610912292; _fbp=fb.1.1610912292358.1831979940; u=2oiycodt.1oaavs8.dyu0a4x7fxw0; v=1610912321; buyer_laas_location=641780; buyer_location_id=641780; luri=novosibirsk; buyer_selected_search_radius4=0_general; buyer_local_priority_v2=0; sx=H4sIAAAAAAACAxXLQQqAIBAF0Lv8dYvRLEdvU0MIBU0iKCHePXr71zGfefd1W5RLYick2kSakiB2VETclpf85n19RJMSp4vJOSlM%2F2BMOBDNaigE9taM8QH0oydNVAAAAA%3D%3D; dfp_group=100; _ym_uid=1610912323905107257; _ym_d=1610912323; _ym_visorc_34241905=b; _ym_isad=2; _ym_visorc_419506=w; _ym_visorc_188382=w; __gads=ID=2cff056a4e50a953-22d0341a94b900a6:T=1610912323:S=ALNI_MZMbOe0285QjW7EVvsYtSa-RA_Vpg;',
'f=5.8696cbce96d2947c36b4dd61b04726f1a816010d61a371dda816010d61a371dda816010d61a371dda816010d61a371ddbb0992c943830ce0bb0992c943830ce0bb0992c943830ce0a816010d61a371dd2668c76b1faaa358c08fe24d747f54dc0df103df0c26013a0df103df0c26013a2ebf3cb6fd35a0ac0df103df0c26013a8b1472fe2f9ba6b978e38434be2a23fac7b9c4258fe3658d831064c92d93c3903815369ae2d1a81d04dbcad294c152cb0df103df0c26013a20f3d16ad0b1c5462da10fb74cac1eab2da10fb74cac1eab3c02ea8f64acc0bdf0c77052689da50d2da10fb74cac1eab2da10fb74cac1eab2da10fb74cac1eab2da10fb74cac1eab91e52da22a560f5503c77801b122405c48ab0bfc8423929a6d7a5083cc1669877def5708993e2ca678f1dc04f891d61e35b0929bad7c1ea5dec762b46b6afe81f200c638bc3d18ce60768b50dd5e12c30e37135e8f7c6b64dc9f90003c0354a346b8ae4e81acb9fa46b8ae4e81acb9fa02c68186b443a7acf8b817f3dc0c3f21c1eac53cc61955882da10fb74cac1eab2da10fb74cac1eab5e5aa47e7d07c0f95e1e792141febc9cb841da6c7dc79d0b'

proxies = [
            "http://6qFwMg:uwHhBX@194.67.219.197:9609", 
            "http://uZ3znH:w1aVx0@193.124.180.6:9077", 
            "http://uZ3znH:w1aVx0@193.124.177.100:9751"
          ]

dev_text = 'Над проектом работали:\n- Альмухаметов Артём (@Mukhachan_dev)\n- Ардашев Александр (@likeaatea)'

import pymysql
from pymysql.cursors import DictCursor
from mysql.connector import Error, pooling
from DataBase import DataBase

def db_connect_old(): # Подключение к БД с обычным соединением (Для приложения и бота) #
    try:
        db = pymysql.connect(
            host = host,
            port = 3306,
            user = user,
            password = password,
            database = db_name,
            cursorclass = DictCursor,
        )  
    except Exception as ex:
        print("[INFO] Ошибка при работе с MySQL: ", ex)
    
    return DataBase(db, db.cursor())


def db_connect_pool(): # Передаём пул соединений (для парсера) #
    try:
        db = pooling.MySQLConnectionPool(
            pool_size = cores,
            pool_reset_session = False,
            host = host,
            port = 3306,
            user = user,
            password = password,
            database = db_name,
        )
        print('Создан пул соединений:', db.pool_name)
        return db 
    except Error as e:
        print('При создании пула возникла ошибка:', e)
