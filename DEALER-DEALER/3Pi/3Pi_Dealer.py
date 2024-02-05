import zmq
import threading
import select

# Dictionary of IP addresses
identity_to_ip = {
    b"lap": "192.168.1.80",
    b"rpi99": "192.168.1.81",
    b"rpi22": "192.168.1.82",
    b"rpi01": "192.168.1.83",
}

# Class to send messages to a dealer 
class MessageSender:
    def __init__(self, dealer_socket, identity_to_ip):
        self.dealer_socket = dealer_socket
        self.identity_to_ip = identity_to_ip
        self.user_identity = None
        self.user_message = None

    def get_user_input(self):
        self.user_identity = input("Enter the identity of the Dealer to send a message to: ").encode('utf-8')
        self.user_message = input(f"Enter message to send to {self.user_identity.decode('utf-8')}: ")

    def send_message_to_pi(self):
        ip_address = self.identity_to_ip.get(self.user_identity, "unknown")
        print(f"Sending message to {self.user_identity.decode('utf-8')} at IP address {ip_address}")
        self.dealer_socket.send_multipart([self.user_identity, self.user_message.encode('utf-8')])

# Function to receive messages from dealer
def receive_messages(dealer_socket):
    while True:
        # Use select to check for input without blocking
        rlist, _, _ = select.select([dealer_socket], [], [], 0.1)
        if rlist:
            identity, message = dealer_socket.recv_multipart()
            received_from = identity.decode('utf-8')
            received_message = message.decode('utf-8')

            # Print received message
            print(f"\nReceived message from {received_from}: {received_message}")

            # Send notification back to the Dealer
            notification_message = f"Received your message: {received_message}"
            dealer_socket.send_multipart([identity, notification_message.encode('utf-8')])

            # Create an instance of MessageSender and call its methods
            message_sender = MessageSender(dealer_socket, identity_to_ip)
            message_sender.get_user_input()
            message_sender.send_message_to_pi()

# Creating ZMQ context
context = zmq.Context()

# Creating a DEALER socket
dealer_socket = context.socket(zmq.DEALER)
dealer_socket.setsockopt_string(zmq.IDENTITY, "lap")  # Unique identity for the laptop
dealer_socket.bind("tcp://*:5555")  # Binding to all available network interfaces

# Creating threads for sending and receiving messages
receive_thread = threading.Thread(target=receive_messages, args=(dealer_socket,))

# Starting the threads
receive_thread.start()

# Prompt user for input in the main thread
while True:
    try:
        input("Press Enter to send a message to a Raspberry Pi...")
    except KeyboardInterrupt:
        break

    message_sender = MessageSender(dealer_socket, identity_to_ip)
    message_sender.get_user_input()
    message_sender.send_message_to_pi()

# Wait for the receive thread to finish
receive_thread.join()

# Closing the dealer socket after the receive thread finishes
dealer_socket.close()
context.term()
