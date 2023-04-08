from config import host, user, password, db_name
from DataBase import DataBase
import pymysql

def db_connect():
    try:
        db = pymysql.connect(
            host = host,
            port = 3306,
            user = user,
            password = password,
            database = db_name,
            cursorclass = pymysql.cursors.DictCursor
        )  
    except Exception as ex:
        print("[INFO] Ошибка при работе с MySQL: ", ex)
    return DataBase(db)
