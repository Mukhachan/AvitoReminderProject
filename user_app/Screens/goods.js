import React from "react";
import { SafeAreaView, Text, StyleSheet } from "react-native";

export const GoodsScreen = () => (
    <SafeAreaView style = {styles.container}>
        <Text>Главное окно - список товаров</Text>
    </SafeAreaView>
)

const styles = StyleSheet.create({
    container: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center'
    }
})

