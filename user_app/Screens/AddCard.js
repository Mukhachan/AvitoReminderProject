import React from "react";
import { SafeAreaView, Text, StyleSheet } from "react-native";

export const AddCard = () => (
    <SafeAreaView style = {styles.container}>
        <Text>Добавить товар</Text>
    </SafeAreaView>
)

const styles = StyleSheet.create({
    container: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center'
    }
})

