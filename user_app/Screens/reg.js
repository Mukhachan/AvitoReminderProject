import React from "react";
import { SafeAreaView, Text, StyleSheet, TextInput, TouchableOpacity } from "react-native";
import { useNavigation } from '@react-navigation/native';

export function RegScreen () {
    let txt = 'Регистрация';
    let login;
    let Fpassword;
    let Spassword;
    
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

    const reg_btn_press = (login, Fpassword, Spassword) => {
        if (Fpassword == undefined || Spassword == undefined || login == undefined ){
            alert('Вы не ввели никаких данных')
        } else if (Fpassword != Spassword) { 
            // Здесь мы обрабатываем случай в котором пароли разные
            alert('Вы ввели разные пароли')
         } else {
            fetch(host+'call_function?function_name=create_user&email='+login+'&password='+Fpassword)
            .then((response) => (response.json()))
            .then((resp) => console.log(resp))
        }
    }

    return (
    <SafeAreaView style = {styles.container}>{circles}
            <Text style={styles.GreetingTxt}>{txt}</Text>

            <Text style={styles.TXT}>Логин</Text>
            <TextInput keyboardType='email-address' style={styles.input} placeholder='email' placeholderTextColor="#525252" 
            onChangeText={(log) => (login = log)}/>

            <Text style={styles.TXT}>Пароль</Text>
            <TextInput secureTextEntry={true} style={styles.input} placeholder='password' placeholderTextColor="#525252" 
            onChangeText={(psw) => (Fpassword = psw)}/>

            <Text style={styles.TXT}>Пароль ещё раз</Text>
            <TextInput secureTextEntry={true} style={styles.input} placeholder='password' placeholderTextColor="#525252" 
            onChangeText={(psw) => (Spassword = psw)}/>

            <TouchableOpacity style={styles.AuthBtn} onPress={() => reg_btn_press(login, Fpassword, Spassword)} >
            <Text style={styles.BTNtxt}>Регистрация</Text>            
            </TouchableOpacity>

            <TouchableOpacity style={{position: 'absolute', bottom: '5%', color:'#000'}}
                onPress={() => console.log('Нажата кнопка: "Забыли пароль?"')}>
              <Text style={{textDecorationLine: 'underline'}}>Забыли пароль?</Text>
            </TouchableOpacity>
            
            <TouchableOpacity style={{position: 'absolute', bottom: '1%', color:'#000'}}
                onPress={() => {HandlNavigateToScreen('Авторизация'); console.log('Нажата кнопка: "Авторизироваться"')}}>
              <Text style= {{textDecorationLine: 'underline'}}>Авторизироваться</Text>
            </TouchableOpacity>            
    </SafeAreaView>
    )
}

const styles = StyleSheet.create({
    container: {
        zIndex: 1,
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center'
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
        fontWeight: 600,
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
        textAlign: 'center'
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
})

