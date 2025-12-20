import { ObjectCaptureScreen } from 'components/ObjectCaptureScreen';
import { StatusBar } from 'expo-status-bar';

import './global.css';

export default function App() {
  return (
    <>
      <ObjectCaptureScreen />
      <StatusBar style="auto" />
    </>
  );
}
