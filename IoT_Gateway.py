from curses import ERR
from glob import glob
import geocoder # Using geocoder library to get the coordinate of the device base on IP
import json
import paho.mqtt.client as mqttclient
import serial
import time

print("IoT Gateway")

BROKER_ADDRESS = "demo.thingsboard.io"
PORT = 1883
THINGS_BOARD_ACCESS_TOKEN = "itjJFJLDL8IUieSfuAB8"

#Status in finite state machine
MAX_FAILURE = 3
IDLE = 0
SEND_ACK = 1
SEND_DATA = 2
WAIT_ACK = 3
ERROR_LOG = 4

mess = ""
bbc_port = "/dev/cu.usbmodem14202"

if len(bbc_port) > 0:
    ser = serial.Serial(port=bbc_port, baudrate=115200)

# Process serial data
serial_data_available = 0
ack_available = 0
ledStatus = False
fanStatus = False
def processData(data):
    global serial_data_available, ack_available
    global ledStatus, fanStatus
    
    data = data.replace("!", "")
    data = data.replace("#", "")
    data = data.split(":")
    print(data)

    #Publish data to the server
    data = {data[1]:data[2]}

    if data[1] == 'ack':
        ack_available = 1
    else:
        serial_data_available = 1

        if data[1] == 'ledValue' or data[1] == 'fanValue':
            cmd = 0
            if data[1] == 'ledValue':
                ledStatus = not ledStatus
                if ledStatus == 0:
                    cmd = 0
                elif ledStatus == 1:
                    cmd = 1
            else:
                fanStatus = not fanStatus
                if ledStatus == 0:
                    cmd = 2
                elif ledStatus == 1:
                    cmd = 3

            client.publish('v1/devices/me/attributes', json.dumps(data), 1)
            sendCmd(cmd) # Update the cmd to control 2 devices
        else:
            client.publish('v1/devices/me/telemetry', json.dumps(data), 1)



def readSerial():
    bytesToRead = ser.inWaiting()
    if (bytesToRead > 0):
        global mess
        mess = mess + ser.read(bytesToRead).decode("UTF-8")
        while ("#" in mess) and ("!" in mess):
            start = mess.find("!")
            end = mess.find("#")
            processData(mess[start:end + 1])
            if (end == len(mess)):
                mess = ""
            else:
                mess = mess[end+1:]
    pass


def subscribed(client, userdata, mid, granted_qos):
    print("Subscribed...")


def sendCmd(cmd):
    if len(bbc_port) > 0:
        ser.write((str(cmd) + "#").encode())
    else:
        raise "Can not send cmd!"
    pass

# Process mqtt data
mqtt_data_available = 0
def recv_message(client, userdata, message):
    global mqtt_data_available
    mqtt_data_available = 1

    temp_data = {'value': True}
    global ledStatus, fanStatus
    cmd = 0

    print("Received: ", message.payload.decode("utf-8"))
    
    try:
        jsonobj = json.loads(message.payload)
        if jsonobj['method'] == "setLED":
            temp_data['value'] = jsonobj['params']
            client.publish('v1/devices/me/attributes', json.dumps(temp_data), 1)
            ledStatus = temp_data['value']
            if ledStatus == 0:
                cmd = 0
            elif ledStatus == 1:
                cmd = 1
        elif jsonobj['method'] == "setFAN":
            temp_data['value'] = jsonobj['params']
            client.publish('v1/devices/me/attributes', json.dumps(temp_data), 1)
            fanStatus = temp_data['value']
            if fanStatus == 0:
                cmd = 2
            elif fanStatus == 1:
                cmd = 3
    except:
        pass

    # Update the cmd to control 2 devices
    sendCmd(cmd)

def connected(client, usedata, flags, rc):
    if rc == 0:
        print("Thingsboard connected successfully!!")
        client.subscribe("v1/devices/me/rpc/request/+")
        return True
    else:
        print("Connection is failed")
        return False

timer_counter, timer_flag = 0, 0
def setTimer(counter):
    global timer_counter, timer_flag
    timer_counter = counter

def cancelTimer():
    global timer_counter, timer_flag
    timer_counter, timer_flag = 0, 0

def runTimer():
    global timer_counter, timer_flag
    timer_counter -= 1
    if timer_counter <= 0:
        timer_flag = 1

def send_ack():
    if len(bbc_port) > 0:
        ser.write(("ack" + "#").encode())

def send_data():
    # Sent in recv_message() function
    pass

client = mqttclient.Client("Gateway_Thingsboard")
client.username_pw_set(THINGS_BOARD_ACCESS_TOKEN)

client.on_connect = connected
client.connect(BROKER_ADDRESS, 1883)
client.loop_start()

client.on_subscribe = subscribed
client.on_message = recv_message

counter = 0
latitude = 0
longitude = 0

status = 0
failure_counter = 0
while True:
    #Update location every 10 seconds
    counter = counter + 1
    if counter == 10:
        counter = 0
        collect_data = {
            'longitude': longitude,
            'latitude': latitude
        }
        
        g = geocoder.ip('me') # Return a list [<latitude>, <longtitude>] base on IP of this pic
        latitude = g.latlng[0]
        longitude = g.latlng[1]

        client.publish('v1/devices/me/telemetry', json.dumps(collect_data), 1)

    # Read serial
    if len(bbc_port) > 0:
        readSerial()

    # Finite State Machine
    print(f"Curent status: %d" % status)
    if status == IDLE:
        if serial_data_available:
            status = SEND_ACK
        elif mqtt_data_available:
            status = SEND_DATA
    elif status == SEND_ACK:
        serial_data_available = 0
        send_ack()
        status = IDLE
    elif status == SEND_DATA:
        mqtt_data_available = 0
        send_data()
        setTimer(5)
        status = WAIT_ACK
    elif status == WAIT_ACK:
        if ack_available:
            cancelTimer()
            ack_available = 0
            status = IDLE
        elif timer_flag:
            failure_counter += 1
            if failure_counter > MAX_FAILURE:
                cancelTimer()
                failure_counter = 0
                status = ERROR_LOG
            else:
                status = SEND_DATA
    elif status == ERROR_LOG:
        print("TIME OUT!!!")
        status = IDLE
    
    runTimer()
    time.sleep(1)
