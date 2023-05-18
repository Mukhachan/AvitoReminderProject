//import * as React from 'react';
import * as SecureStore from 'expo-secure-store';
import axios from 'axios';
import { host } from './host';

export async function save(key, value) {
    console.log('Пытаемся сохранить')
    await SecureStore.setItemAsync(key, value);
  }

export async function getValueFor(key) {
    let token = await SecureStore.getItemAsync(key);

    if (token != undefined || token != null) {
        const config = {
            baseURL: host+'call_function?function_name=get_user_state',
            headers: {headers: { Authorization: `${token}` }}
        }
        try {
            result = await axios.get(config.baseURL, config.headers);
            console.log(result.data)
        } catch (error) {
            console.log(error)
            return null
        }
        //result.data.result[1] // Это полный путь до возвращённого состояния авторизации
        await save('auth_state', result.data.result[1])
        return result.data.result[1]

    } else {
        return false
    }
}