import React from "react";
import { SafeAreaView, Text, StyleSheet } from "react-native";

export const RegScreen = () => (
    <SafeAreaView style = {styles.container}>
        <Text>Регистрация</Text>
    </SafeAreaView>
)

const styles = StyleSheet.create({
    container: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center'
    }
})

