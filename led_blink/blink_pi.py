import zmq
import pigpio
import os
import time

## Killing previous pigpiod and jackd background processes
os.system('sudo killall pigpiod')

# Starting pigpiod
os.system('sudo pigpiod -t 0 -l -x 1111110000111111111111110000')
time.sleep(1)

# Raspberry Pi Identity
pi_identity = "rpi26"

# Making a context to receive blink state information 
blink_context = zmq.Context()
blink_socket = blink_context.socket(zmq.DEALER)

# Setting the identity of the socket in bytes
blink_socket.identity = bytes(f"{pi_identity}", "utf-8") 

# Connecting to IP address (192.168.0.99 for laptop, 192.168.0.207 for seaturtle)
router_ip = "tcp://192.168.0.207:55" 
blink_socket.connect(router_ip) 

# Send the identity of the Raspberry Pi to the server
blink_socket.send_string(f"{pi_identity}") 

# Print acknowledgment
print(f"Connected to router at {router_ip}") 

# Set up pigpio 
pig = pigpio.pi()

