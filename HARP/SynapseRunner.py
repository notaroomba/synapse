import socket
import struct
import cv2
import numpy as np
from ultralytics import YOLO

SERVER_IP = '10.1.33.148'
PORT = 1100
MODEL_NAME = 'yolov8n.pt'
CONFIDENCE = 0.5

def start_server():
    print("Loading YOLO model...")
    model = YOLO(MODEL_NAME)
    print(f"Model loaded. Starting server on Port {PORT}...")

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind((SERVER_IP, PORT))
        server_socket.listen(1)
        print(f"Server Listening! IP: {socket.gethostbyname(socket.gethostname())}, Port: {PORT}")
    except Exception as e:
        print(f"Error binding server: {e}")
        return

    while True:
        try:
            client_socket, addr = server_socket.accept()
            print(f"Connected to Quest at: {addr}")
            handle_client(client_socket, model)
        except KeyboardInterrupt:
            print("\nServer stopping...")
            break
        except Exception as e:
            print(f"Connection error: {e}")

def handle_client(conn, model):
    try:
        while True:
            size_data = recv_all(conn, 4)
            if not size_data:
                break
            
            image_size = struct.unpack('<I', size_data)[0]
            
            image_bytes = recv_all(conn, image_size)
            if not image_bytes:
                break

            nparr = np.frombuffer(image_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame is None:
                continue

            results = model(frame, verbose=False, conf=CONFIDENCE)
            
            detections = []
            for r in results:
                for box in r.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    cls_id = int(box.cls[0])
                    label_name = model.names[cls_id]
                    
                    det_str = f"{label_name},{int(x1)},{int(y1)},{int(x2)},{int(y2)}"
                    detections.append(det_str)
            
            response_str = "|".join(detections)
            
            if not response_str:
                response_str = "EMPTY"

            response_bytes = response_str.encode('utf-8')
            conn.sendall(struct.pack('<I', len(response_bytes)))
            conn.sendall(response_bytes)

    except Exception as e:
        print(f"Client disconnected or error: {e}")     
    finally:
        conn.close()

def recv_all(sock, n):
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return data

if __name__ == '__main__':
    start_server()