import socket
import struct
import numpy as np
import cv2
import onnxruntime as ort

SERVER_IP = "0.0.0.0"
VIDEO_PORT = 11000
QUEST_DATA_PORT = 11001

ESP_IP = "192.168.1.100" 
ESP_PORT = 8000

MODEL_PATH = "yolov8n.onnx"
CONF_THRESHOLD = 0.5
INPUT_SIZE = 640

class AMDDetector:
    def __init__(self, model_path):
        try:
            self.session = ort.InferenceSession(model_path, providers=['DmlExecutionProvider'])
            print(f" [GPU] Model loaded on AMD DirectML.")
        except Exception as e:
            print(f" [CPU] Warning: DirectML failed, using CPU. Error: {e}")
            self.session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])

        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

    def detect(self, img):
        img_h, img_w = img.shape[:2]

        input_img = cv2.resize(img, (INPUT_SIZE, INPUT_SIZE))
        input_img = cv2.cvtColor(input_img, cv2.COLOR_BGR2RGB)
        input_img = input_img / 255.0
        input_img = input_img.transpose(2, 0, 1)
        input_tensor = np.expand_dims(input_img, axis=0).astype(np.float32)

        outputs = self.session.run([self.output_name], {self.input_name: input_tensor})
        
        predictions = np.squeeze(outputs[0]).T
        scores = np.max(predictions[:, 4:], axis=1)
        
        if len(scores) > 0:
            best_idx = np.argmax(scores)
            confidence = scores[best_idx]
            
            if confidence > CONF_THRESHOLD:
                box = predictions[best_idx, :4]
                
                n_x = (box[0] - box[2]/2) / INPUT_SIZE
                n_y = (box[1] - box[3]/2) / INPUT_SIZE
                n_w = box[2] / INPUT_SIZE
                n_h = box[3] / INPUT_SIZE
                
                return (n_x, n_y, n_w, n_h), confidence

        return None, 0.0

def send_esp_command(is_detected):
    msg = "DETECTED:1" if is_detected else "DETECTED:0"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(msg.encode(), (ESP_IP, ESP_PORT))
    except: pass

def send_quest_feedback(client_ip, box):
    msg = f"BOX:{box[0]:.3f},{box[1]:.3f},{box[2]:.3f},{box[3]:.3f}"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(msg.encode(), (client_ip, QUEST_DATA_PORT))
    except: pass

def start_server():
    print(" [INIT] Loading Neural Network...")
    detector = AMDDetector(MODEL_PATH)
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind((SERVER_IP, VIDEO_PORT))
    print(f" [ONLINE] Listening for Quest on port {VIDEO_PORT}...")

    frame_buffer = {}

    while True:
        try:
            packet, addr = server_socket.recvfrom(65536)
            if len(packet) < 8: continue

            frame_id = struct.unpack('I', packet[0:4])[0]
            seq_id = struct.unpack('H', packet[4:6])[0]
            total_packets = struct.unpack('H', packet[6:8])[0]
            payload = packet[8:]

            if frame_id not in frame_buffer: frame_buffer[frame_id] = {}
            frame_buffer[frame_id][seq_id] = payload

            if len(frame_buffer[frame_id]) == total_packets:
                full_data = b''.join([frame_buffer[frame_id].get(i, b'') for i in range(total_packets)])
                
                np_arr = np.frombuffer(full_data, dtype=np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

                if frame is not None:
                    box, conf = detector.detect(frame)
                    
                    if box:
                        send_esp_command(True)
                        send_quest_feedback(addr[0], box)
                        
                        h, w = frame.shape[:2]
                        x1 = int(box[0] * w)
                        y1 = int(box[1] * h)
                        x2 = int((box[0] + box[2]) * w)
                        y2 = int((box[1] + box[3]) * h)
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(frame, f"Person: {conf:.2f}", (x1, y1-10), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                    else:
                        send_esp_command(False)

                    cv2.imshow("Synapse Server (AMD)", frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'): break

                del frame_buffer[frame_id]
                old_frames = [k for k in frame_buffer if k < frame_id - 10]
                for k in old_frames: del frame_buffer[k]

        except Exception as e:
            print(f"Error: {e}")
            break

    server_socket.close()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    start_server()