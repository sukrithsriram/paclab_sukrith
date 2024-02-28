import zmq
import threading

# Function to send messages to the Raspberry Pi
def send_messages():
    while True:
        message_to_raspberry = input("Enter message to send to Raspberry Pi: ")
        dealer_socket.send_string(message_to_raspberry)

# Function to receive messages from the Raspberry Pi
def receive_messages():
    while True:
        reply_from_raspberry = dealer_socket.recv_string()
        print(f"Received reply from Raspberry Pi: {reply_from_raspberry}")

# Creating ZMQ context
context = zmq.Context()

# Creating a DEALER socket
dealer_socket = context.socket(zmq.DEALER)
dealer_socket.bind("tcp://*:5555") # Binding to all available network interfaces

# Creating threads for sending and receiving messages
send_thread = threading.Thread(target=send_messages)
receive_thread = threading.Thread(target=receive_messages)

# Starting the threads
send_thread.start()
receive_thread.start()

# Joining the threads
send_thread.join()
receive_thread.join()
