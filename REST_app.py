from flask import Flask, request, jsonify
from flask_cors import CORS, cross_origin
from config import db_connect_old

app = Flask(__name__)
app.config['CORS_HEADERS'] = 'Content-Type'
cors = CORS(app, resources={r"/foo": {"origins": "*"}})


@app.route('/call_function', methods=['GET'])
@cross_origin(origin='*',headers=['Content-Type','Authorization'])
def call_function():
    # получаем имя функции и ее аргументы из параметров запроса
    function_name = request.args.get('function_name')
    kwargs = {}
    for key, value in request.args.items():
        if key != 'function_name':
            kwargs[key] = value

    # проверяем, что имя функции задано и соответствует существующей функции
    if function_name:
        # получаем экземпляр класса DataBase и вызываем нужную функцию, передавая ей именованные аргументы
        try:
            conn = db_connect_old()
            result = getattr(conn, function_name)(**kwargs)
            
            # возвращаем результат в виде JSON
            return jsonify({'result': result})            
        
        except Exception:
            return jsonify({'error': 'Invalid function name'})

        finally:
            del conn
    else:
        # возвращаем сообщение об ошибке в виде JSON
        return jsonify({'error': 'Invalid function name'})
        

if __name__ == '__main__':
    app.run(host = '0.0.0.0', port = 5000, debug = True)
