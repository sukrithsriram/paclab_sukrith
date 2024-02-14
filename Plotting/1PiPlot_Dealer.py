import zmq
import time

# Raspberry Pi's identity 
pi_identity = b"rpi99"

# Creating a ZeroMQ context and socket for communication with the laptop
context = zmq.Context()
socket = context.socket(zmq.DEALER)
socket.identity = pi_identity
socket.connect("tcp://192.168.1.80:5555")  # Connecting to laptop IP address

while True:
    try:
        # Sending the Pi number to the laptop
        pi_number = 1  # Number of the Pi that has to be made green
        print(f"Sending Pi = {pi_number} to the Laptop") # Statement to show that the message is being sent
        socket.send_string(str(pi_number))

        # Waiting for acknowledgment from the laptop
        response = socket.recv_string()
        if response == "ACK":
            print("- Pi = 1 Received by Laptop")

        # Waiting for 2 seconds before sending the next message
        time.sleep(2)

    except KeyboardInterrupt:
        break

# Closing the socket and context when done
socket.close()
context.term()
