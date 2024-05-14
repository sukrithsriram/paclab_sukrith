import zmq
import threading

# Function to receive messages from the laptop
def receive_messages():
    while True:
        request_from_laptop = dealer_socket.recv_string() 
        print(f"Received request from laptop: {request_from_laptop}") # Decoding the message from bytes to a string

        # Processing the request
        reply_to_laptop = f"Reply to {request_from_laptop}"

        # Sending the reply back to the laptop
        dealer_socket.send_string(reply_to_laptop)

# Function to send messages to the laptop
def send_messages():
    while True:
        message_to_laptop = input("Enter message to send to laptop: ") 
        dealer_socket.send_string(message_to_laptop) 

# Creating ZMQ context
context = zmq.Context()

# Creating a DEALER socket
dealer_socket = context.socket(zmq.DEALER)
dealer_socket.connect("tcp://192.168.1.80:5555")  # Laptop IP address

# Creating threads for sending and receiving messages
receive_thread = threading.Thread(target=receive_messages)
send_thread = threading.Thread(target=send_messages)

# Starting the threads
receive_thread.start()
send_thread.start()

# Joining the threads
receive_thread.join()
send_thread.join()
