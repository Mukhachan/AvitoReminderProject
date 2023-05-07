import { NavigationContainer } from '@react-navigation/native';

// Импорт навигатора
 import { AppNavigator } from './AppNavigator.js'


export default function App() {

  return (
    <NavigationContainer>
      <AppNavigator/>
    </NavigationContainer>
  );

};
