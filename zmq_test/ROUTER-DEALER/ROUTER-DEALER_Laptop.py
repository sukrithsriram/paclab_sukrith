import zmq

# Creating ZMQ context
context = zmq.Context()

# Creating a ROUTER socket
router_socket = context.socket(zmq.ROUTER)
router_socket.bind("tcp://*:5555") # Binding to all available network interfaces

# Loop to receive and send messages
try:
    while True:
        # Receiving a message from the laptop
        identity, _, message = router_socket.recv_multipart()
        print(f"Laptop received message from {identity}: {message.decode('utf-8')}") # Decoding the message from bytes to a string

        # Processing and sending a response back to the sender
        response = input(f"Enter a response for {identity.decode('utf-8')}: ")
        router_socket.send_multipart([identity, b"", response.encode('utf-8')]) # Encoding the message from a string to bytes

# Exiting the loop
finally:
    router_socket.close()
    context.term()
