import zmq
import threading

identity_to_ip = {
    b"lap": "192.168.1.80",
    b"rpi99": "192.168.1.81",
    b"rpi22": "192.168.1.82",
    b"rpi01": "192.168.1.83",
}

def device(identity, bind_address, connect_addresses):
    context = zmq.Context()
    
    # DEALER socket for sending messages
    send_socket = context.socket(zmq.DEALER)
    send_socket.setsockopt(zmq.IDENTITY, identity)
    send_socket.bind(bind_address)

    # DEALER socket for receiving messages
    recv_socket = context.socket(zmq.DEALER)
    recv_socket.setsockopt(zmq.IDENTITY, identity)
    for address in connect_addresses:
        recv_socket.connect(address)

    def send_messages():
        while True:
            # Prompt for the identity to send the message to
            to_identity = input("Enter the identity to send the message to (lap/rpi99/rpi22/rpi01): ").encode()
            
            if to_identity.lower() == 'exit':
                break

            message = input("Enter message to send (or 'exit' to quit): ")
            if message.lower() == 'exit':
                break

            # Send message to the specified identity
            send_socket.send_multipart([to_identity, message.encode()])

    def receive_messages():
        while True:
            try:
                # Receive message and identity
                identity, message = recv_socket.recv_multipart(zmq.NOBLOCK)
                
                sender_ip = identity_to_ip.get(identity, "Unknown IP")
                print(f"Received message from {sender_ip}: {message.decode()}")
            except zmq.Again:
                pass

    send_thread = threading.Thread(target=send_messages)
    recv_thread = threading.Thread(target=receive_messages)

    send_thread.start()
    recv_thread.start()

    send_thread.join()
    recv_thread.join()

    send_socket.close()
    recv_socket.close()
    context.term()

if __name__ == "__main__":
    # Identity for the dealer
    identity = b"lap"
    
    # Bind and Connect Addresses for the dealer
    bind_address = "tcp://*:5555"
    connect_addresses = ["tcp://192.168.1.81:5555", "tcp://192.168.1.82:5555", "tcp://192.168.1.83:5555"]

    device_thread = threading.Thread(target=device, args=(identity, bind_address, connect_addresses))
    device_thread.start()

    device_thread.join()
