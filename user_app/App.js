import React from 'react';
import { StyleSheet, Text, SafeAreaView, TouchableOpacity, TextInput } from 'react-native';

export default function App() {
  let txt = 'Добро\nпожаловать!';
  let login;
  let password;
  let value = ''; 
  // let data = fetch('http://45.9.41.88:5000/call_function?function_name=parsing_data_read')
  //   .then((response) => response.json())
  //   .then((resp) => console.log(resp));
  const auth_btn_press = (login, password) =>{
    console.log('Нажата кнопка: "Войти"')
    console.log(login)
    console.log(password)
  }


  return (
    <SafeAreaView style={styles.container}>
      <Text style={styles.GreetingTxt}>{txt}</Text>

      <Text style={styles.TXT}>Логин</Text>
      <TextInput style={styles.input} placeholder='email' placeholderTextColor="#000" 
        defaultValue={value} onChangeText={() => (login = this.value)}/>
      
      <Text style={styles.TXT}>Пароль</Text>
      <TextInput style={styles.input} placeholder='password' placeholderTextColor="#000" 
        defaultValue={value} onChangeText={() => (password = this.value)}/>
      
      <TouchableOpacity style={styles.AuthBtn} onPress={() => auth_btn_press(login, password)} >
        <Text style={styles.BTNtxt}>Войти</Text>
      </TouchableOpacity>
      
      <TouchableOpacity style={{position: 'absolute', bottom: '5%', color:'#000'}}
        onPress={() => console.log('Нажата кнопка: "Забыли пароль?"')}>
        <Text>Забыли пароль?</Text>
      </TouchableOpacity>
      
      <TouchableOpacity style={{position: 'absolute', bottom: '1%', color:'#000'}}
        onPress={() => console.log('Нажата кнопка: "Зарегистрироваться?"')}>
        <Text>Зарегистрироваться?</Text>
      </TouchableOpacity>

    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
    alignItems: 'center',
    justifyContent: 'center',
    margin: 10,
  },
  GreetingTxt: {
    fontSize: 28,
    fontWeight: 700,
    textAlign: 'center',
    marginBottom: 24,
  },
  TXT: {
    fontSize: 20
  },
  input: {
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
    color: '#fff',
    fontSize: 24,
  },
  AuthBtn: {
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
    shadowOpacity: 0.44,
    shadowRadius: 10.32,
    
    elevation: 16,
  },
  links: {
    
    bottom: 0,
  }
});
