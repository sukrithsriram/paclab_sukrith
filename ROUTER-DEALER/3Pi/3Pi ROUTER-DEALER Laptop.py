import zmq

# Creating ZMQ context
context = zmq.Context()

# Creating a ROUTER socket
router_socket = context.socket(zmq.ROUTER)
router_socket.identity = b"lap"  # Set the identity of the router
router_socket.bind("tcp://*:5555")  # Binding to all available network interfaces

# Dictionary of IP addresses for three Raspberry Pis
identity_to_ip = {
    b"rpi99": "192.168.1.81",
    b"rpi22": "192.168.1.82",
    b"rpi1": "192.168.1.83",
}

# Loop to receive and send messages
try:
    while True:
        # Receiving a message from a Raspberry Pi
        identity, _, message = router_socket.recv_multipart()
        print(f"Received message from {identity}: {message.decode('utf-8')}")

        # Ignoring messages from unknown identities
        if identity not in identity_to_ip:
            print(f"Unknown identity {identity.decode('utf-8')}. Ignoring message.")
            continue

        # Getting the IP address from the dictionary
        ip_address = identity_to_ip[identity]

        # Processing and sending a response back to the sender
        response = input(f"Enter a response for {identity.decode('utf-8')} ({ip_address}): ")
        router_socket.send_multipart([identity, b"", response.encode('utf-8')])

# Exiting the loop
finally:
    router_socket.close()
    context.term()
