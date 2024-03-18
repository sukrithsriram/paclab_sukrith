import zmq
import pigpio

# Raspberry Pi's identity (you can customize this)
pi_identity = b"rpi01"

# Creating a ZeroMQ context and socket for communication with the central system
context = zmq.Context()
socket = context.socket(zmq.DEALER)
socket.identity = pi_identity
socket.connect("tcp://192.168.0.194:5555")  # Connecting to Laptop IP address

# Pigpio configuration
a_state = 0
count = 0
nosepoke_pin = 14
nosepoke_id = 3

# Callback functions for nosepoke pin (When the nosepoke is detected)
def poke_detected(pin, level, tick): 
    global a_state, count, nosepoke_id
    a_state = 1
    count += 1
    nosepoke_id = 3  # Set the nosepoke_id here, you can customize it
    print("Poke Detected!")
    print("Poke Count:", count)
    
    # Sending nosepoke_id wirelessly
    try:
        print(f"Sending nosepoke_id = {nosepoke_id} to the Laptop") 
        socket.send_string(str(nosepoke_id))
    except Exception as e:
        print("Error sending nosepoke_id:", e)

# Callback function for nosepoke pin (When the nosepoke is completed)
def poke_out(pin, level, tick):
    global a_state
    a_state = 0
    print("Poke Completed")

# Set up pigpio and callbacks
pi = pigpio.pi()
pi.callback(nosepoke_pin, pigpio.RISING_EDGE, poke_detected)
pi.callback(nosepoke_pin, pigpio.FALLING_EDGE, poke_out)

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
