import pigpio

a_state = 0
count = 0

def poke_detected(pin, level, tick): #  Callback function triggered when pulse A is detected.
    global a_state, count
    a_state = 1
    count += 1
    print("Poke Detected!")
    print("Poke Count: ", count)

def poke_down(pin, level, tick): # Callback function triggered when pulse A goes down.
    global a_state
    a_state = 0
    print("Poke Completed")

pi = pigpio.pi()
pi.callback(14, pigpio.RISING_EDGE, poke_detected)
pi.callback(14, pigpio.FALLING_EDGE, poke_down)

try:
    while True:
        pass
except KeyboardInterrupt:
    pi.stop()
