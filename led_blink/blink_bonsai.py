import zmq

# Making a context to send blink state information to all pis
blink_context = zmq.Context()
blink_socket = blink_context.socket(zmq.ROUTER)
blink_socket.bind("tcp://*:5555")

# Setting a state variable to be modified by bonsai
blink_state =  False

# Set of all the Pi identities it is connected to 
identities = set()

# Receive message from the socket
identity, message = blink_socket.recv_multipart()
identities.add(identity)

# Logic to send message to pis if the state is set to true in bonsai
if blink_state == True:
    for identity in identities:
        blink_socket.send_multipart([identity, bytes(f"blink", 'utf-8]')])
elif blink_state == False:
    for identity in identities:
        blink_socket.send_multipart([identity, bytes(f"stop", 'utf-8]')])


