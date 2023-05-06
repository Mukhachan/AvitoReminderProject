import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';

// Импорт навигатора
// import { Stack } from './AppNavigator.js'

// Импорты ниже это отдельные части приложения
import { AuthFunction } from './Screens/auth.js'
import { RegScreen } from './Screens/reg.js'
import { GoodsScreen } from './Screens/goods.js'


const Stack = createNativeStackNavigator();


export default function App() {

  return (
    <NavigationContainer>
      <Stack.Navigator>
        <Stack.Screen name="Авторизация" component={AuthFunction} />
        <Stack.Screen name="Регистрация" component={RegScreen}></Stack.Screen>
      </Stack.Navigator>
    </NavigationContainer>
  );

};
