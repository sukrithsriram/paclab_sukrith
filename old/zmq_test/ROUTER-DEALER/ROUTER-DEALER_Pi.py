import zmq
import time

# Creating ZMQ context
context = zmq.Context()

# Creating a DEALER socket
dealer_socket = context.socket(zmq.DEALER)
dealer_socket.identity = b"RPi99" # Setting the identity of the DEALER socket
dealer_socket.connect("tcp://192.168.1.80:5555")  # Laptop IP address

# Loop to send and receive messages
try:
    while True:
        user_input = input("Enter a message (or 'exit' to quit): ")
        if user_input.lower() == 'exit':
            break
        dealer_socket.send_multipart([b"", user_input.encode('utf-8')])

       # Receive and display the response from the router
        _, response = dealer_socket.recv_multipart()  # Receive all parts of the message
        print(f"Response: {response.decode('utf-8')}")  # Decode the message from bytes to a string
        time.sleep(1)

# Exiting the loop
finally:
    dealer_socket.close()
    context.term()
