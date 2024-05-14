import zmq

# Creating ZMQ context
context = zmq.Context()

# Creating a DEALER socket
dealer_socket = context.socket(zmq.DEALER)
dealer_socket.identity = b"rpi99"  # Set the identity of the dealer
dealer_socket.connect("tcp://192.168.1.80:5555")  # Connecting to the router

# Loop to send messages to the router
try:
    while True:
        # Sending a message to the router
        message = input("Enter a message to send to the laptop: ")
        dealer_socket.send_multipart([b"", message.encode('utf-8')])

        # Receiving a response from the router
        response = dealer_socket.recv_multipart()
        identity, response_data = response[0], response[1]

        print(f"Received response from {identity}: {response_data.decode('utf-8')}")

except KeyboardInterrupt:
    pass

# Closing the dealer socket and terminating the context
finally:
    dealer_socket.close()
    context.term()
