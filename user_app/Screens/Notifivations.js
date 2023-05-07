import React from "react";
import { SafeAreaView, Text, StyleSheet } from "react-native";

export const Notifications = () => (
    <SafeAreaView style = {styles.container}>
        <Text>Уведомления</Text>
    </SafeAreaView>
)

const styles = StyleSheet.create({
    container: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center'
    }
})

