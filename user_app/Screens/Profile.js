import React from "react";
import { SafeAreaView, Text, StyleSheet } from "react-native";

export const Profile = () => (
    <SafeAreaView style = {styles.container}>
        <Text>Профиль</Text>
    </SafeAreaView>
)

const styles = StyleSheet.create({
    container: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center'
    }
})

