import React from "react";
import { SafeAreaView, Text, StyleSheet, TouchableOpacity, TextInput } from "react-native";

export const Profile = () => (
    <SafeAreaView style = {styles.container}>
        <TextInput style={styles.input} placeholder="логин"/>
        <TextInput style={styles.input} placeholder="пароль"/>
    </SafeAreaView>
)

const styles = StyleSheet.create({
    container: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center'
    },
    input: {
        textAlign: 'center',
        backgroundColor: '#b8b8b8',
        margin: 10,
        borderRadius: 14,
        borderColor: 'black',
        width: '75%'
    }
})

