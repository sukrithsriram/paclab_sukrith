import zmq
import threading

# Function to receive messages from other Raspberry Pis
def receive_messages():
    while True:
        identity, message = dealer_socket.recv_multipart()
        print(f"Received message from {identity.decode('utf-8')}: {message.decode('utf-8')}")

# Function to send messages to other Raspberry Pis
def send_messages():
    while True:
        identity = input("Enter the identity of the Raspberry Pi to send a message to: ").encode('utf-8')
        message_to_pi = input(f"Enter message to send to {identity.decode('utf-8')}: ")
        dealer_socket.send_multipart([identity, message_to_pi.encode('utf-8')])

# Creating ZMQ context
context = zmq.Context()

# Creating a DEALER socket
dealer_socket = context.socket(zmq.DEALER)
dealer_socket.setsockopt_string(zmq.IDENTITY, "rpi99")  # Unique identity for this Raspberry Pi
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
