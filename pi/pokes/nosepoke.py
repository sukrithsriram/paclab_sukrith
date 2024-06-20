import zmq
import pigpio
import numpy as np
import os
import jack
import time
import threading
import random
import json
import socket as sc

# TODO: move these methods into a Nosepoke object. That object should be
# defined in another script and imported here
a_state = 0
count = 0
nosepoke_pinL = 8
nosepoke_pinR = 15
nosepokeL_id = params['nosepokeL_id']
nospokeR_id = params['nosepokeR_id']

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
        if params['nosepokeL_type'] == "901":
            pi.write(17, 1)
        elif params['nosepokeL_type'] == "903":
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
        if params['nosepokeR_type'] == "901":
            pi.write(10, 1)
        elif params['nosepokeR_type'] == "903":
            pi.write(10, 0)
            
    # Reset poke detected flags
    right_poke_detected = False

# Callback functions for nosepoke pin (When the nosepoke is detected)
def poke_detectedL(pin, level, tick): 
    global a_state, count, left_poke_detected
    a_state = 1
    count += 1
    left_poke_detected = True
    print("Poke Completed (Left)")
    print("Poke Count:", count)
    nosepoke_idL = params['nosepokeL_id']  # Set the left nosepoke_id here according to the pi
    pi.set_mode(17, pigpio.OUTPUT)
    if params['nosepokeL_type'] == "901":
        pi.write(17, 0)
    elif params['nosepokeL_type'] == "903":
        pi.write(17, 1)
        
    # Sending nosepoke_id wirelessly
    try:
        print(f"Sending nosepoke_id = {nosepoke_idL}") 
        poke_socket.send_string(str(nosepoke_idL))
    except Exception as e:
        print("Error sending nosepoke_id:", e)

def poke_detectedR(pin, level, tick): 
    global a_state, count, right_poke_detected
    a_state = 1
    count += 1
    right_poke_detected = True
    print("Poke Completed (Right)")
    print("Poke Count:", count)
    nosepoke_idR = params['nosepokeR_id']  # Set the right nosepoke_id here according to the pi
    pi.set_mode(10, pigpio.OUTPUT)
    if params['nosepokeR_type'] == "901":
        pi.write(10, 0)
    elif params['nosepokeR_type'] == "903":
        pi.write(10, 1)

    # Sending nosepoke_id wirelessly
    try:
        print(f"Sending nosepoke_id = {nosepoke_idR}") 
        poke_socket.send_string(str(nosepoke_idR))
    except Exception as e:
        print("Error sending nosepoke_id:", e)

def open_valve(port):
    """Open the valve for port
    
    port : TODO document what this is
    TODO: reward duration needs to be a parameter of the task or mouse # It is in the test branch
    """
    if port == int(params['nosepokeL_id']):
        pi.set_mode(6, pigpio.OUTPUT)
        pi.write(6, 1)
        time.sleep(0.05)
        pi.write(6, 0)
    
    if port == int(params['nosepokeR_id']):
        pi.set_mode(26, pigpio.OUTPUT)
        pi.write(26, 1)
        time.sleep(0.05)
        pi.write(26, 0)

# TODO: document this function
def flash():
    pi.set_mode(22, pigpio.OUTPUT)
    pi.write(22, 1)
    pi.set_mode(11, pigpio.OUTPUT)
    pi.write(11, 1)
    time.sleep(0.5)
    pi.write(22, 0)
    pi.write(11, 0)  
