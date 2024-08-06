import zmq
import pigpio
import os
import time

## Killing previous pigpiod and jackd background processes
os.system('sudo killall pigpiod')

# Starting pigpiod
os.system('sudo pigpiod -t 0 -l -x 1111110000111111111111110000')

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

# Creating a ZMQ Poller
poller = zmq.Poller()
poller.register(blink_socket, zmq.POLLIN)

# Set up pigpio 
pig = pigpio.pi()

# Initializing LED parameters 
#led_pin =  27
pwm_frequency = 1
pwm_duty_cycle = 50

try:
    # Setting led pin for the light to flash 
    led_pin = 27

    while True:
        socks = dict(poller.poll(100))

        if blink_socket in socks and socks[blink_socket] == zmq.POLLIN:
            # Blocking receive
            msg = blink_socket.recv_string()

            # Logic for messages
            if msg == 'blink':
                # Making LED pin blink
                pig.set_mode(led_pin, pigpio.OUTPUT)
                pig.set_PWM_frequency(led_pin, pwm_frequency)
                pig.set_PWM_dutycycle(led_pin, pwm_duty_cycle) 

                # Debug Message
                print("Blinking LED")    

            elif msg == 'stop':
                # Stop LED blinking
                pig.write(led_pin, 0)

                # Debug Statement
                print("Blinking Stopped")
except KeyboardInterrupt:
    # Stops the pigpio connection
    pig.stop()    

finally:
# Close all sockets and contexts
    blink_socket.close()
    blink_context.term()    
          




