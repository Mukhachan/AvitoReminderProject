import { StatusBar } from 'expo-status-bar';
import React from 'react';
import { StyleSheet, Text, SafeAreaView, Button } from 'react-native';

export default function App() {
  let txt = 'Текст';

  fetch('http://45.9.41.88:5000/call_function?function_name=parsing_data_read')
    .then((response) => response.json())
    .then((data) => console.log('Вот что вернул сервер', data));

  return (
    <SafeAreaView style={styles.container}>
      <Text>{txt}</Text>
      <Button title='Название кнопки' onPress={() => console.log('Кнопка нажата') } />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
    alignItems: 'center',
    justifyContent: 'center',
    margin: 10
  },
});
