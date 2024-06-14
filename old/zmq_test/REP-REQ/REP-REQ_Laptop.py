# Request-Reply Pattern
import zmq
import time

# Creating ZMQ context
context = zmq.Context()

# Creating a REQ socket
socket = context.socket(zmq.REQ)
socket.connect("tcp://192.168.1.81:5555")  # IP address of Raspberry Pi 

# Loop to send and receive messages 
while True:
    message = input("Message to Raspberry Pi: ")
    
    # Sending the message to Raspberry Pi
    socket.send_string(message)
    
    # Waiting for the reply from Raspberry Pi
    reply = socket.recv_string()
    print(f"Reply from Raspberry Pi: {reply}")
    
    time.sleep(1)  
