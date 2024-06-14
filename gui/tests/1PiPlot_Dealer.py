import zmq
import time
import random

# Raspberry Pi's identity (you can customize this)
pi_identity = b"rpi99"

# Creating a ZeroMQ context and socket for communication with the central system
context = zmq.Context()
socket = context.socket(zmq.DEALER)
socket.identity = pi_identity
socket.connect("tcp://192.168.1.80:5555")  # Connecting to Laptop IP address

while True:
    try:
        # Sending the Pi number to the central system
        pi_number = 3  # Number of the Pi that has to be made green
        print(f"Sending Pi = {pi_number} to the Laptop") # Statement to show that the message is being sent
        socket.send_string(str(pi_number))

        # Waiting for acknowledgment from the central system
        response = socket.recv_string()
        if response == "ACK":
            print(f"- Pi = {pi_number} Received by Laptop")

        # Waiting for 2 seconds before sending the next message
        random_sleep = random.randint(1, 4)
        time.sleep(random_sleep)

    except KeyboardInterrupt:
        break

# Closing the socket and context when done
socket.close()
context.term()
