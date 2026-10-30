import time
import utime
import gsm
import machine
import json
from machine import Pin, PWM
from time import sleep

#physical limits, dont get past these
MIN_SERVO = 3.1
MAX_SERVO = 11.2

def load_config():
    with open("config.json", "r") as f:
        return json.load(f)

def save_config(config):
    with open("config.json", "w") as f:
        json.dump(config, f)

config = load_config()

SERVO_HOME = config["servo_home"]
SERVO_END = config["servo_end"]

servo = PWM(Pin(14), freq=50)
servo.duty(SERVO_END)

def invoke_button_press():
    servo.duty(SERVO_END)
    sleep(1.5)

    servo.duty(SERVO_HOME)
    sleep(1)

    servo.duty(SERVO_END)
    sleep(1)

def gsm_module_power():
    GSM_PWR = Pin(4, Pin.OUT)
    GSM_RST = Pin(5, Pin.OUT)
    GSM_MODEM_PWR = Pin(23, Pin.OUT)

    GSM_PWR.value(0)
    GSM_RST.value(1)
    GSM_MODEM_PWR.value(1)


def gsm_start(led_pin):
    led_pin.value(0)
    gsm.stop() # in case we are retrying a connection, just to be safe

    time.sleep(1)

    gsm.start(tx=27, rx=26, apn='', user='', password='')

    time_start = utime.time()

    while(utime.time() - time_start < 20):
            print(".",end="")
            status = gsm.status()

            if status[0] == 89:
                return True

            time.sleep(0.5)

    return False


def setup_gsm_clock():
    gsm.atcmd('AT+CLTS=1') # enable gsm RTC time sync
    gsm.atcmd('AT+COPS=2') # unregister from network
    time.sleep(3)
    gsm.atcmd('AT+COPS=0') # register to network (needed for AT+CLTS to take effect)

    reregister_time = utime.time()

    while(utime.time() - reregister_time < 20):
        gsm_clock = gsm.atcmd('AT+COPS?', printable=True)

        if (gsm_clock[9:12] == '0,0'):
            return True

        print(".", end="")
        time.sleep(1)

    return False


def read_gsm_clock():
    return gsm.atcmd("AT+CCLK?", printable=True)


def net_quality():
    net_quality = gsm.atcmd('AT+CSQ', printable=True)
    spl = net_quality.split(" ")
    res = int(spl[1].split(",")[0])

    if (res < 0 or res > 31): # valid values are 0-31
        return "--"
    return round(res * 100 / 31)


def status_sms(ADMIN_NUMBERS, boot_at):
    indexes = gsm.checkSMS(status=gsm.SMS_UNREAD)

    if indexes:
        for i in indexes:
            msg = gsm.readSMS(i, True)
            
            if msg is None or len(msg) < 7:
                continue

            if msg[2] not in ADMIN_NUMBERS:
                continue

            command = msg[6].strip().upper().split()
            if not command:
                continue
            
            print("debug got sms")

            if command[0] == 'STATUS':
                text = "Boot: {}, NQ: {}%".format(last_boot(boot_at), net_quality())
                gsm.sendSMS(msg[2], text)
                
            elif command[0] == 'REBOOT':
                gsm.sendSMS(msg[2], "Rebooting...")
                time.sleep(2)
                machine.reset()
                
            elif command[0] == 'BLACKLIST':
                config = load_config()
                gsm.sendSMS(msg[2], str(config['blocked_numbers']))
                
            elif command[0] == 'ADMINS':
                gsm.sendSMS(msg[2], str(ADMIN_NUMBERS))
                
            elif command[0] == 'HELP':
                gsm.sendSMS(msg[2], "STATUS, REBOOT, BLACKLIST, ADMINS, SERVO, SERVOHOME <float>, SERVOEND <float>, BLOCK <nr>, WHITE <nr>, ADMINADD <nr>, ADMINREMOVE <nr>")
                
            elif command[0] == 'BLOCK' and len(command) > 1:
                add_to_blocklist(msg[2], command[1])
            
            elif command[0] == 'WHITE' and len(command) > 1:
                remove_from_blacklist(msg[2], command[1])
            
            elif command[0] == 'ADMINADD' and len(command) > 1:
                add_admin(msg[2], command[1])
            
            elif command[0] == 'ADMINREMOVE' and len(command) > 1:
                remove_admin(msg[2], command[1])
            
            elif command[0] == 'SERVO':
                print("GOT SERVO SMS")
                explain_servo(msg[2])
                
            elif command[0] == 'SERVOHOME' and len(command) > 1:
                set_servo_home(msg[2], command[1])
                
            elif command[0] == 'SERVOEND' and len(command) > 1:
                set_servo_end(msg[2], command[1])

def set_servo_end(admin_phone_number, servo_end):
    config = load_config()
    
    servo_end = parse_float(servo_end)
    
    if not servo_end:
        gsm.sendSMS(admin_phone_number, "Wrong value. Must be float compatible.")
        return

    if servo_end == config['servo_end']:
        gsm.sendSMS(admin_phone_number, "Same value exists. No changes made.")
        return    
    
    if servo_end < MIN_SERVO or servo_end > MAX_SERVO:
        gsm.sendSMS(admin_phone_number, "Allowed range: " + str(MIN_SERVO) + "< X <" + str(MAX_SERVO))
        return
    
    if servo_end <= config['servo_home']:
        gsm.sendSMS(admin_phone_number, "END <= HOME???")
        return
    
    config['servo_end'] = servo_end
    save_config(config)
    
    gsm.sendSMS(admin_phone_number, "New SERVO_END set to: " + str(servo_end))
    
    time.sleep(2)
    machine.reset()
    
def set_servo_home(admin_phone_number, servo_home):
    config = load_config()
    
    servo_home = parse_float(servo_home)
    
    if not servo_home:
        gsm.sendSMS(admin_phone_number, "Wrong value. Must be float compatible.")
        return

    if servo_home == config['servo_home']:
        gsm.sendSMS(admin_phone_number, "Same value exists. No changes made.")
        return

    if servo_home < MIN_SERVO or servo_home > MAX_SERVO:
        gsm.sendSMS(admin_phone_number, "Allowed range: " + str(MIN_SERVO) + "< X <" + str(MAX_SERVO))
        return
    
    if servo_home >= config['servo_end']:
        gsm.sendSMS(admin_phone_number, "HOME >= END???")
        return
    
    config['servo_home'] = servo_home
    save_config(config)
    
    gsm.sendSMS(admin_phone_number, "New SERVO_HOME set to: " + str(servo_home))
    
    time.sleep(2)
    machine.reset()

def explain_servo(admin_phone_number):
    print("EXPLAININ SERVO")
    config = load_config()

    gsm.sendSMS(admin_phone_number, "SERVO_HOME=" + str(config['servo_home']) + ", SERVO_END=" + str(config['servo_end']) + ". Range (" + str(MIN_SERVO) + "-" + str(MAX_SERVO) + ")")
    return

def add_to_blocklist(admin_phone_number, command_phone_number):
    config = load_config()
    if command_phone_number in config["blocked_numbers"]:
        gsm.sendSMS(admin_phone_number, "Already blacklisted.")
        return

    config["blocked_numbers"].append(command_phone_number)
    save_config(config)
    
    gsm.sendSMS(admin_phone_number, command_phone_number + " blacklisted.")
    
    time.sleep(2)
    machine.reset()
        
def remove_from_blacklist(admin_phone_number, command_phone_number):
    config = load_config()
    if command_phone_number not in config["blocked_numbers"]:
        gsm.sendSMS(admin_phone_number, "Number not blackisted.")
        return

    config["blocked_numbers"].remove(command_phone_number)
    save_config(config)
    
    gsm.sendSMS(admin_phone_number, command_phone_number + " removed from the blacklist.")
    
    time.sleep(2)
    machine.reset()

def add_admin(admin_phone_number, command_phone_number):
    config = load_config()
    if command_phone_number in config["admin_numbers"]:
        gsm.sendSMS(admin_phone_number, "Already an admin.")
        return

    config["admin_numbers"].append(command_phone_number)
    save_config(config)
    
    gsm.sendSMS(admin_phone_number, command_phone_number + " added to admins.")
    
    time.sleep(2)
    machine.reset()

def remove_admin(admin_phone_number, command_phone_number):
    config = load_config()
    if command_phone_number not in config["admin_numbers"]:
        gsm.sendSMS(admin_phone_number, "Number not an admin.")
        return
    
    if len(config["admin_numbers"]) < 2:
        gsm.sendSMS(admin_phone_number, "Can't remove last admin.")
        return

    config["admin_numbers"].remove(command_phone_number)
    save_config(config)
    
    gsm.sendSMS(admin_phone_number, command_phone_number + " removed from admin list.")
    
    time.sleep(2)
    machine.reset()
    
def burglary():
    pass

def color_led():
    pass

def last_boot(boot_at):
    try:
        part = boot_at.split(" ")[1]
        dt = part.split("+")[0]
        return dt[1:].replace(",", " ")
    except:
        return "n/a"

def parse_float(value):
    try:
        return float(value.replace(",", "."))
    except:
        return None

def loop(BLOCKED_NUMBERS, ADMIN_NUMBERS, boot_at):
    loop_index = 0

    print("\nWaiting for incomming calls...")

    while(gsm.atcmd('AT+CREG?', printable=True).split(" ")[1][2] == '1'):
        caller_id = gsm.atcmd('AT+CLCC', printable=True).split(",") # includes callers phone number in case of incomming call
        incomming_call = False

        if len(caller_id) > 2 and caller_id[2] == '4':
            incomming_call = True

        if incomming_call:
            gsm.atcmd('ATH') #hangup

            caller_number = caller_id[5].replace('"', '') # phone number extraction

            print("\nIncomming call from: {}".format(caller_number))

            if caller_number in BLOCKED_NUMBERS:
                print('\nPiece of shit calling. DENIED.')
            else:
                #print("FAKE BUTTON PRESS FOR DEBUG")
                invoke_button_press()
        
        loop_index += 1
        if loop_index >= 6: # check sms every 6 loops (~3 secs)
            status_sms(ADMIN_NUMBERS, boot_at)
            loop_index = 0

        print("*", end="")
        time.sleep(0.5)

    machine.reset() # if the while loop ended it means we are no longer connected - reboot
