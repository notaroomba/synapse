declare module 'react-native-object-capture' {
  import { ViewProps } from 'react-native';
  import React from 'react';

  export interface ObjectCaptureViewProps extends ViewProps {
    checkpointDirectory: string;
    imagesDirectory: string;
    onPointCloud?: (data: any) => void;
  }

  const ObjectCaptureView: React.ComponentType<ObjectCaptureViewProps>;
  export default ObjectCaptureView;
}
