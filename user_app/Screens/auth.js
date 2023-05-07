import { StyleSheet, Text, SafeAreaView, TouchableOpacity, TextInput } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { setToken } from '../App.js';
import { AppNavigator } from '../AppNavigator.js'

export function AuthFunction() {
  let txt = 'Добро\nпожаловать!';
  let login;
  let password;

  const navigation = useNavigation()
  const HandlNavigateToScreen = (screen) => {
    navigation.navigate(screen)
  }

  const circles = [];
  const colours = ['#FF0000', '#8A0BED', '#13EA00']
  for (let i = 0; i < 3; i++) {
    const size = 100; // генерируем размер круга
    const x = Math.floor(Math.random() * 300); // генерируем случайную координату по оси X
    const y = Math.floor(Math.random() * 500); // генерируем случайную координату по оси Y
    
    circles.push(
      <SafeAreaView
        key={i}
        style={[
          styles.circle,
          { width: size, 
            height: size, 
            left: x, 
            top: y, 
            backgroundColor: colours[i] } ]}/>
    )
  }
  
  const auth_btn_press = (login, password) =>{
    console.log('Нажата кнопка: "Войти"')
    console.log(login, password)

    if (login == undefined && password == undefined) {
      alert('Введите данные')
    }
    else {
      let url = 'http://45.9.41.88:5000/call_function?function_name=get_user&email=' + login + '&password=' + password

      fetch(url)
      .then((response) => (response.json()))
      // .then( response => console.log(response) )
      .then(((resp) => {
        console.log(resp)
        if (resp.result[1]) {
          alert('Успешная авторизация!')
          
          // И тут мы типо сохраняем токен на мобиле и переходим к другому окну
          // addToken(resp.result[2])
          signedIn = true
          
          //navigation.navigate('Tab')

        } else {
          alert('Ты кто такой???')
        }
      })
      )
      .catch((e) => console.log('Тут появилась пренеприятнейшая ошибка\n',e))
      }
    }

  return (
    <SafeAreaView style={styles.container}>{circles}
      
      <Text style={styles.GreetingTxt}>{txt}</Text>

      <Text style={styles.TXT}>Логин</Text>
      <TextInput keyboardType='email-address' style={styles.input} placeholder='email' placeholderTextColor="#525252" 
        onChangeText={(log) => (login = log)}/>
      
      <Text style={styles.TXT}>Пароль</Text>
      <TextInput secureTextEntry='true' style={styles.input} placeholder='password' placeholderTextColor="#525252" 
        onChangeText={(psw) => (password = psw)}/>
      
      <TouchableOpacity style={styles.AuthBtn} onPress={() => auth_btn_press(login, password)} >
        <Text style={styles.BTNtxt}>Войти</Text>
      </TouchableOpacity>
      
      <TouchableOpacity style={{position: 'absolute', bottom: '5%', color:'#000'}}
        onPress={() => console.log('Нажата кнопка: "Забыли пароль?"')}>
        <Text style={{textDecorationLine: 'underline'}}>Забыли пароль?</Text>
      </TouchableOpacity>
      
      <TouchableOpacity style={{position: 'absolute', bottom: '1%', color:'#000'}}
        onPress={() => {HandlNavigateToScreen('Регистрация'); console.log('Нажата кнопка: "Зарегистрироваться"')}}>
        <Text style= {{textDecorationLine: 'underline'}}>Зарегистрироваться</Text>
      </TouchableOpacity>
      
    </SafeAreaView>
  );
}
  
  const styles = StyleSheet.create({
    container: {
      zIndex: 1,
      flex: 1,
      backgroundColor: '#fff',
      alignItems: 'center',
      justifyContent: 'center',
      margin: 10,
    },
    circle: {
      zIndex: 0,
      position: 'absolute',
      borderRadius: 50,
      backgroundColor: 'green',

      shadowColor:'#000',
      elevation: 14,
      shadowOffset: {
        width: 0,
        height: 2,
      },
      shadowOpacity: 0.4,
      shadowRadius: 4
    },

    GreetingTxt: {
      zIndex: 1,
      fontSize: 32,
      fontWeight: 650,
      textAlign: 'center',
      marginBottom: 28,
    },
    TXT: {
      zIndex: 1,
      fontSize: 24
    },
    input: {
      zIndex: 1,
      textAlign: 'center',
      fontSize: 20,
      
      height: 44,
      width: '90%',
      backgroundColor: '#b8b8b8',
      margin: 10,
      borderRadius: 14,
      borderColor: 'black',
      
      shadowColor:'#000',
      elevation: 14,
      shadowOffset: {
        width: 0,
        height: 2,
      },
      shadowOpacity: 0.4,
      shadowRadius: 4
    },
    BTNtxt : {
      zIndex: 1,
      color: '#fff',
      fontSize: 24,
    },
    AuthBtn: {
      zIndex: 1,
      marginTop: 14,
      backgroundColor: '#007AFF',
      borderRadius: 18,
      height: 35,
      width: '60%',
      justifyContent: 'center',
      alignItems: 'center',
  
      shadowColor: "#000",
      shadowOffset: {
        width: 0,
        height: 8,
      },
      shadowOpacity: 0.5,
      shadowRadius: 10,
      
      elevation: 16,
    },
    links: {
      zIndex: 1,
      bottom: 0,
    }
  });
  