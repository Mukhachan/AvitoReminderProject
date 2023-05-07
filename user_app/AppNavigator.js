import * as React from 'react';
import { StyleSheet } from 'react-native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createMaterialBottomTabNavigator } from '@react-navigation/material-bottom-tabs';
import MaterialCommunityIcons from 'react-native-vector-icons/MaterialCommunityIcons';

// Импорты ниже это отдельные части приложения
import { AuthFunction } from './Screens/auth.js'
import { RegScreen } from './Screens/reg.js'
import { GoodsScreen } from './Screens/goods.js'
import { AddCard } from './Screens/AddCard.js';
import { Notifications } from './Screens/Notifivations.js'
import { Profile } from './Screens/Profile.js';

globalThis.signedIn = false;

export const  AppNavigator = () => {
    const Stack = createNativeStackNavigator();
    const Tab = createMaterialBottomTabNavigator();

    const TabStack = () => {
        return (
        <Tab.Navigator 
            barStyle = {styles.itemStyle}
            activeColor="#525252"
            inactiveColor="#525252"
            screenOptions = {() => ({
                showLabel: false,
            })}>

            <Tab.Screen name="Home" tabBarColor='#fff' component={GoodsScreen} options={{
                tabBarLabel: null,
                tabBarIcon: () => (
                    <MaterialCommunityIcons name="home" color='white' size={26} />
                  ),
            }}/>
            <Tab.Screen name="AddCard" component={AddCard} options={{
                tabBarLabel: null,
                tabBarIcon: () => (
                    <MaterialCommunityIcons name="playlist-plus" color='white' size={26} />
                  ),              
            }} />
            <Tab.Screen name="Notifications" component={Notifications} options={{
                tabBarLabel: null,
                tabBarIcon: () => (
                    <MaterialCommunityIcons name="bell" color='white' size={26} />
                  ),                
            }}/>
            <Tab.Screen name="Profile" component={Profile} options={{
                tabBarLabel: null,
                tabBarIcon: () => (
                    <MaterialCommunityIcons name="account-outline" color='white' size={26} />
                  ),                
            }} />
        </Tab.Navigator>
        )
    }

    // Если пользователь не авторизован
    if (signedIn == false) {
        return (
        <Stack.Navigator screenOptions={{headerShown: false}}>
            <Stack.Screen name="Регистрация" component={RegScreen} />
            <Stack.Screen name="Авторизация" component={AuthFunction} />
        </Stack.Navigator>
        )    
    } 
    // Если юзер Авторизован, отображаются эти окна
    else if (signedIn == true) {

        return ( 
        <Stack.Navigator screenOptions={{headerShown: false}}>
            <Stack.Screen name="Tab" options={{
                detachPreviousScreen: 'true',
                gesturesEnabled: false
            }} component={TabStack} />
        </Stack.Navigator>
        )       
    }
}

const styles = StyleSheet.create({
    itemStyle: {
        backgroundColor: '#525252',
        color: '#fff'
    },
    barStyle: {
        tabBarLabel: '',
        backgroundColor: '#525252',
        color: '#fff'
    },
})
