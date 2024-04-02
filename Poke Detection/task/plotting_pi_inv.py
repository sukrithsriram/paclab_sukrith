import zmq
import pigpio

# Raspberry Pi's identity (Change this to the identity of the Raspberry Pi you are using)
pi_identity = b"rpi99"

# Creating a ZeroMQ context and socket for communication with the central system
context = zmq.Context()
socket = context.socket(zmq.DEALER)
socket.identity = pi_identity

# Connect to the server
router_ip = "tcp://192.168.0.194:5555" # Connecting to Laptop IP address (192.168.0.99 for lab setup)
socket.connect(router_ip) 
socket.send_string("rpi99") 
print(f"Connected to router at {router_ip}")  # Print acknowledgment

# Pigpio configuration
a_state = 0
count = 0
nosepoke_pinL = 8
nosepoke_pinR = 15

# Global variables for which nospoke was detected
left_poke_detected = False
right_poke_detected = False

# Callback function for nosepoke pin (When the nosepoke is completed)
def poke_inL(pin, level, tick):
    global a_state, left_poke_detected
    a_state = 0
    if left_poke_detected:
        # Write to left pin
        print("Left poke detected!")
        pi.set_mode(17, pigpio.OUTPUT)
        pi.write(17, 0)

    # Reset poke detected flags
    left_poke_detected = False

# Callback function for nosepoke pin (When the nosepoke is completed)
def poke_inR(pin, level, tick):
    global a_state, right_poke_detected
    a_state = 0
    if right_poke_detected:
        # Write to left pin
        print("Right poke detected!")
        pi.set_mode(10, pigpio.OUTPUT)
        pi.write(10, 1)

    # Reset poke detected flags
    right_poke_detected = False

# Callback functions for nosepoke pin (When the nosepoke is detected)
def poke_detectedL(pin, level, tick): 
    global a_state, count, left_poke_detected
    a_state = 1
    count += 1
    left_poke_detected = True
    # Your existing poke_detectedL code here
    print("Poke Completed (Left)")
    print("Poke Count:", count)
    nosepoke_idL = 1  # Set the left nosepoke_id here according to the pi
    pi.set_mode(17, pigpio.OUTPUT)
    pi.write(17, 1)
    try:
        print(f"Sending nosepoke_id = {nosepoke_idL} to the Laptop") 
        socket.send_string(str(nosepoke_idL))
    except Exception as e:
        print("Error sending nosepoke_id:", e)

def poke_detectedR(pin, level, tick): 
    global a_state, count, right_poke_detected
    a_state = 1
    count += 1
    right_poke_detected = True
    # Your existing poke_detectedR code here
    print("Poke Completed (Right)")
    print("Poke Count:", count)
    nosepoke_idR = 3  # Set the right nosepoke_id here according to the pi
    pi.set_mode(10, pigpio.OUTPUT)
    pi.write(10, 0)
    # Sending nosepoke_id wirelessly
    try:
        print(f"Sending nosepoke_id = {nosepoke_idR} to the Laptop") 
        socket.send_string(str(nosepoke_idR))
    except Exception as e:
        print("Error sending nosepoke_id:", e)

# Set up pigpio and callbacks
pi = pigpio.pi()
pi.callback(nosepoke_pinL, pigpio.FALLING_EDGE, poke_inL)
pi.callback(nosepoke_pinL, pigpio.RISING_EDGE, poke_detectedL)
pi.callback(nosepoke_pinR, pigpio.FALLING_EDGE, poke_inR)
pi.callback(nosepoke_pinR, pigpio.RISING_EDGE, poke_detectedR)

# Main loop to keep the program running and exit when it receives an exit command
try:
    # Initialize reward_pin variable
    reward_pin = None
    current_pin = None  # Track the currently active LED
    
    while True:
        
        # Check for incoming messages
        try:
            msg = socket.recv_string(zmq.NOBLOCK)
            if msg == 'exit':
                pi.write(17, 0)
                pi.write(10, 0)
                pi.write(27, 0)
                pi.write(9, 0)
                print("Received exit command. Terminating program.")
                break  # Exit the loop
            
            elif msg.startswith("Reward Port:"):
                print(msg)
                # Extract the integer part from the message
                msg_parts = msg.split()
                if len(msg_parts) != 3 or not msg_parts[2].isdigit():
                    print("Invalid message format.")
                    continue
                
                value = int(msg_parts[2])  # Extract the integer part
                
                # Reset the previously active LED if any
                if current_pin is not None:
                    pi.write(current_pin, 0)
                    #print("Turning off green LED.")
                
                # Manipulate pin values based on the integer value
                if value == 1:
                    # Manipulate pins for case 1
                    reward_pin = 27  # Example pin for case 1 (Change this to the actual)
                    pi.set_mode(reward_pin, pigpio.OUTPUT)
                    pi.set_PWM_frequency(reward_pin, 1)
                    pi.set_PWM_dutycycle(reward_pin, 50)
                    print("Turning Nosepoke 1 Green")
                    # Update the current LED
                    current_pin = reward_pin

                elif value == 3:
                    # Manipulate pins for case 2
                    reward_pin = 9  # Example pin for case 2
                    pi.set_mode(reward_pin, pigpio.OUTPUT)
                    pi.set_PWM_frequency(reward_pin, 1)
                    pi.set_PWM_dutycycle(reward_pin, 50)
                    print("Turning Nosepoke 3 Green")

                    # Update the current LED
                    current_pin = reward_pin

                else:
                    print(f"Current Port: {value}")
            
            elif msg == "Reward Poke Completed":
                # Turn off the currently active LED
                if current_pin is not None:
                    pi.write(current_pin, 0)
                    print("Turning off currently active LED.")
                    current_pin = None  # Reset the current LED
                else:
                    print("No LED is currently active.")
            else:
                print("Unknown message received:", msg)

        except zmq.Again:
            pass  # No messages received
        
except KeyboardInterrupt:
    pi.stop()
finally:
    socket.close()
    context.term()
