import zmq
import time

# Creating ZMQ context
context = zmq.Context()

# Creating a REP socket
socket = context.socket(zmq.REP)
socket.bind("tcp://*:5555") # Binding to all available network interfaces

while True:
    # Waiting for a request from the laptop
    message = socket.recv_string()
    print(f"Received request from laptop: {message}")
    
    # Processing the request 
    reply = f"Reply from Raspberry Pi: {message}"
    
    # Sending the reply back to the laptop
    socket.send_string(reply)
    
    time.sleep(1)  
