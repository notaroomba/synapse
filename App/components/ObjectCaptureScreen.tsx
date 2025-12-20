// @ts-nocheck
import React, { useEffect, useRef, useState } from 'react';
import { Alert, Linking, Platform, Text, View, SafeAreaView, Pressable } from 'react-native';
import { Camera } from 'expo-camera';

// The native module is optional — we try to render it if available and fall back to a simulator
// @ts-ignore
import ObjectCaptureView from 'react-native-object-capture';

export const ObjectCaptureScreen = () => {
  const [permission, setPermission] = useState<string>('not-determined');
  const [connected, setConnected] = useState(false);
  const [sending, setSending] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const intervalRef = useRef<any>(null);

  useEffect(() => {
    (async () => {
      const { status } = await Camera.getCameraPermissionsAsync();
      setPermission(status);
    })();

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      wsRef.current?.close();
    };
  }, []);

  const requestPermission = async () => {
    const { status } = await Camera.requestCameraPermissionsAsync();
    setPermission(status);
    if (status !== 'granted') {
      Alert.alert('Camera permission needed', 'Please grant camera permission in your Settings');
    }
  };

  const openSettings = () => Linking.openSettings();

  const connectWs = () => {
    if (wsRef.current) return;
    const host = Platform.OS === 'android' ? '10.0.2.2' : 'localhost';
    const ws = new WebSocket(`ws://${host}:8081`);

    ws.onopen = () => setConnected(true);
    ws.onmessage = (evt) => console.log('From server:', evt.data);
    ws.onerror = (err) => console.error('WebSocket error:', err);
    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
    };

    wsRef.current = ws;
  };

  const disconnectWs = () => {
    wsRef.current?.close();
    wsRef.current = null;
    setConnected(false);
  };

  const sendPointCloud = (pc: any) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      Alert.alert(
        'WebSocket not connected',
        'Connect to the WebSocket server before sending pointclouds'
      );
      return;
    }

    try {
      wsRef.current.send(JSON.stringify({ type: 'pointcloud', timestamp: Date.now(), data: pc }));
    } catch (err) {
      console.error('Send failed:', err);
    }
  };

  const startSim = () => {
    if (!connected) {
      Alert.alert('Not connected', 'Connect to the WebSocket server first');
      return;
    }
    setSending(true);
    intervalRef.current = setInterval(() => {
      const points = Array.from({ length: 256 }).map(() => ({
        x: Math.random(),
        y: Math.random(),
        z: Math.random(),
      }));
      sendPointCloud(points);
    }, 500);
  };

  const stopSim = () => {
    setSending(false);
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  };

  const handlePointCloud = (data: any) => {
    if (connected) sendPointCloud(data);
    else console.warn('Point cloud produced but WebSocket is not connected');
  };

  return (
    <SafeAreaView className="flex-1 items-center justify-center bg-white p-4">
      <View className="w-full max-w-2xl">
        <Text className="mb-2 text-lg text-gray-700">Camera permission: {permission}</Text>

        <View className="mb-3 flex-row space-x-2">
          <Pressable onPress={requestPermission} className="rounded bg-blue-600 px-4 py-2">
            <Text className="text-white">Request Camera</Text>
          </Pressable>
          <Pressable onPress={requestPermission} className="rounded bg-gray-600 px-4 py-2">
            <Text className="text-white">Ask Again</Text>
          </Pressable>
          <Pressable onPress={openSettings} className="rounded bg-gray-400 px-4 py-2">
            <Text className="text-black">Settings</Text>
          </Pressable>
        </View>

        <View className="flex-row space-x-2">
          <Pressable
            onPress={connected ? disconnectWs : connectWs}
            className={
              connected ? 'rounded bg-red-600 px-4 py-2' : 'rounded bg-green-600 px-4 py-2'
            }>
            <Text className="text-white">{connected ? 'Disconnect WS' : 'Connect WS'}</Text>
          </Pressable>

          <Pressable
            onPress={sending ? stopSim : startSim}
            className={sending ? 'rounded bg-red-500 px-4 py-2' : 'rounded bg-blue-500 px-4 py-2'}>
            <Text className="text-white">{sending ? 'Stop Sim' : 'Start Sim'}</Text>
          </Pressable>
        </View>

        <View className="mt-6">
          <View className="relative h-60 w-80 overflow-hidden rounded bg-black">
            <Text className="absolute left-3 top-2 z-10 text-xl font-bold text-white">Synapse</Text>
            {/* @ts-ignore */}
            <ObjectCaptureView
              checkpointDirectory={'/tmp/objectcapture-checkpoints'}
              imagesDirectory={'/tmp/objectcapture-images'}
              onPointCloud={handlePointCloud}
              style={{ width: 320, height: 240, backgroundColor: '#000' }}
            />
          </View>
        </View>
      </View>
    </SafeAreaView>
  );
};
