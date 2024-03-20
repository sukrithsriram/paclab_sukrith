import zmq
import pigpio

# Raspberry Pi's identity (Change this to the identity of the Raspberry Pi you are using)
pi_identity = b"rpi99"

# Creating a ZeroMQ context and socket for communication with the central system
context = zmq.Context()
socket = context.socket(zmq.DEALER)
socket.identity = pi_identity
socket.connect("tcp://192.168.0.99:5555")  # Connecting to Laptop IP address (192.168.0.99 for lab setup)

# Pigpio configuration
a_state = 0
count = 0
nosepoke_pinL = 8
nosepoke_pinR = 15
nosepoke_id = 3

# Callback function for nosepoke pin (When the nosepoke is completed)
def poke_in(pin, level, tick):
    global a_state
    a_state = 0
    print("Poke Detected!")

# Callback functions for nosepoke pin (When the nosepoke is detected)
def poke_detectedL(pin, level, tick): 
    global a_state, count, nosepoke_id
    a_state = 1
    count += 1
    nosepoke_idL = 3  # Set the left nosepoke_id here according to the pi
    print("Poke Completed (Left)", pi_identity)
    print("Poke Count:", count)
    
    # Sending nosepoke_id wirelessly
    try:
        print(f"Sending nosepoke_id = {nosepoke_idL} to the Laptop") 
        socket.send_string(str(nosepoke_idL))
    except Exception as e:
        print("Error sending nosepoke_id:", e)

# Callback functions for nosepoke pin (When the nosepoke is detected)
def poke_detectedR(pin, level, tick): 
    global a_state, count, nosepoke_id
    a_state = 1
    count += 1
    nosepoke_idR = 4  # Set the right nosepoke_id here according to the pi
    print("Poke Completed (Right)", pi_identity)
    print("Poke Count:", count)
    
    # Sending nosepoke_id wirelessly
    try:
        print(f"Sending nosepoke_id = {nosepoke_idR} to the Laptop") 
        socket.send_string(str(nosepoke_idR))
    except Exception as e:
        print("Error sending nosepoke_id:", e)

# Set up pigpio and callbacks
pi = pigpio.pi()
pi.callback(nosepoke_pinL, pigpio.FALLING_EDGE, poke_in)
pi.callback(nosepoke_pinL, pigpio.RISING_EDGE, poke_detectedL)
pi.callback(nosepoke_pinR, pigpio.FALLING_EDGE, poke_in)
pi.callback(nosepoke_pinR, pigpio.RISING_EDGE, poke_detectedR)

# Main loop to keep the program running and exit when it receives an exit command
try:
    while True:
        # Check for incoming messages
        try:
            msg = socket.recv_string(zmq.NOBLOCK)
            if msg == 'exit':
                print("Received exit command. Terminating program.")
                break  # Exit the loop
        except zmq.Again:
            pass  # No messages received
        
except KeyboardInterrupt:
    pi.stop()
finally:
    socket.close()
    context.term()
