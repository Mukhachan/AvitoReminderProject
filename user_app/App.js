import { NavigationContainer } from '@react-navigation/native';
// Импорт компонетноу
import { AppNavigator } from './AppNavigator.js'
// import { getValueFor } from './StorageComponent.js';


export default function App() {
  return (
    <NavigationContainer>
      <AppNavigator/>
    </NavigationContainer>
  );

};
