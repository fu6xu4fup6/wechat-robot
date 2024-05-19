#!/usr/bin/python3.9
import asyncio
import requests
import json
import socket
import struct
import signal
import sys
import select
import json
from urllib.parse import urlparse, parse_qs
import os
from loguru import logger

'''
auther: Hui
version: 1
modify date: 2024.05.01
功能: 消息队列for wechat robot
新增: logger,从tcp调整成udp
'''

# 限制每分钟发送请求的次数
REQUESTS_PER_MINUTE = 20
# 一分钟的秒数
ONE_MINUTE = 60
# queue 最大值
MAX_SIZE = 100
# 请求包头部
HEADER = {'Content-Type': 'application/json;charset=utf-8'}

'''
计时器的字典
字典一开始是空的
sec是过了几秒钟,60秒后归0
count是60s内收到几次讯息，最高为20次(机器人限制一分钟内只能20次)
status是对应微信机器人通道是不是锁着，1为正常:0为锁
'''

timer = {}
MAX_LOG_FILE_SIZE  = 1024 * 1024 

# 服务器ip及端口
HOST = ""
PORT = 54321
LOCK = True

# 计算校验和
def cal_checksum(data):    
    checksum = sum(data) & 0xFF
    return checksum

def check_packet(packet):
    if len(packet) < 1024:
        logger.error("Error: Incomplete packet received.")
        return False
    
    pack_header = packet[:4]
    if pack_header != b'HEAD':
        logger.error("Error: Invalid packet header.")
        return False
    
    data_len = struct.unpack('!I', packet[4:8])[0]
    json_data = packet[8:8+data_len]
    if data_len != len(json_data):
        logger.error("Error: Incorrect data length in packet.")
        return False
    received_check_sum = packet[8 + data_len]
    calculated_check_sum = cal_checksum(json_data)
    if calculated_check_sum != received_check_sum:
        logger.error("Error: Checksum mismatch.")
        return False
    
    return True



async def handle_timer():
    global timer,LOCK
    i = 0
    while LOCK:
        for k in list(timer):
            if i % 10 == 0:
                timer[k]["sec"] += 1
                parsed_url = urlparse(k)
                query_params = parse_qs(parsed_url.query)
                key_value = query_params.get('key', [''])[0]
                print(str(key_value)+":"+str(timer[k]["sec"])+":"+str(timer[k]["count"])+":"+str(timer[k]["status"]))
            if timer[k]["count"] == 20:
                if timer[k]["sec"] < 60:
                    timer[k]["sec"] = 0
                    timer[k]["count"] = 0
                    timer[k]["status"] = 0
        
            if timer[k]["sec"] == 60:
                if timer[k]["status"] == 0:
                    timer[k]["sec"] = 0
                    timer[k]["count"] = 0
                    timer[k]["status"] = 1
                else:
                    del timer[k]
        if i == 600:
            i = 0
            logger.info("run")
        i += 1
        await asyncio.sleep(0.1)

# 0.1秒收一次packet到queue
async def read_from_socket(msg_queue):
    global LOCK
    udp_socket_server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket_server.bind((HOST,PORT))
    udp_socket_server.setblocking(False)
    #loop = asyncio.get_event_loop()
    i = 0
    while LOCK:
        try:
            ready_to_read, _, _ = select.select([udp_socket_server], [], [], 0)
            if udp_socket_server in ready_to_read:
                data, addr = udp_socket_server.recvfrom(1024)
                logger.info(f"connected by {addr}...")
                if data:
                    await msg_queue.put(data)
            #3.11才支持...
            #data,addr = await loop.sock_recvfrom(udp_socket_server,1024)
        #except asyncio.TimeoutError as e:
        except socket.timeout:
            logger.error(e)
            pass
        except socket.error as e:
            logger.error(e)
            if e.errno == 10035:
                pass
        await asyncio.sleep(0.1)
       

async def send_requests(msg_queue):
    global timer,LOCK
    while LOCK:
        try:
            packet = await asyncio.wait_for(msg_queue.get(),timeout=1)
            if check_packet(packet):
                data_len = struct.unpack('!I', packet[4:8])[0]
                json_data = json.loads(packet[8:8+data_len].decode('utf-8'))
                api_url = json_data["url"]
                #dumps把json转成string，不然"会变成'，json格式不接受
                msg = json.dumps(json_data["data"])
        
                if api_url not in timer:
                    #先锁一分钟，因为微信机器人有一分钟20包的限制
                    timer[api_url] = {"count":0,"sec":0,"status":0}
                if timer[api_url]["status"] == 1:
                    if timer[api_url]["count"] < REQUESTS_PER_MINUTE:
                        response = requests.post(api_url, data=msg,headers=HEADER).content
                        print(response)
                        logger.info(f"{response}...")
                        timer[api_url]["count"] += 1
                else:
                    await msg_queue.put(packet)
        except asyncio.TimeoutError:
            pass
       

        await asyncio.sleep(0.5)

def signal_handler(signal,frame):
    global LOCK
    print('I caught the Bomber!')
    LOCK = False
    sys.exit(0)
 
signal.signal(signal.SIGINT,signal_handler)

def check_path_exist(path):
    if not os.path.exists(path):
        try:
            os.makedirs(path)
            logger.debug(f"Created log directory: {path}")
        except OSError as e:
            logger.debug(f"Failed to create log directory: {path}, Error: {e}")
            raise

def init_logger():
    current_path = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(current_path, 'log')
    check_path_exist(log_path)
    log_file_location = os.path.join(log_path, 'msg_queue.log')
    logger.remove(handler_id=None)
    logger.add(sink=log_file_location,level="DEBUG",compression="zip",enqueue=True,rotation="2 MB")
    logger.add(sink=sys.stderr,level="INFO")

def load_config():
    global HOST,PORT
    logger.info("load config")
    try:
        with open('./config.json', 'r') as f:
            config = json.load(f)
            HOST = config['host']
            PORT = config['port']
    except FileNotFoundError:
        logger.warning("Config file not found. Creating default config.")
        config = {'host': "127.0.0.1", 'port': 54321}
        with open('./config.json', 'w') as f:
            json.dump(config, f, indent=4)
    except json.JSONDecodeError:
        logger.error("Error decoding JSON in config file.")

    logger.info(f"Config loaded: HOST={HOST}, PORT={PORT}")

async def main():
    init_logger()
    load_config()
    msg_queue = asyncio.Queue(maxsize=MAX_SIZE)
    timer_task = asyncio.create_task(handle_timer())
    consumer_task = asyncio.create_task(send_requests(msg_queue))
    producer_task = asyncio.create_task(read_from_socket(msg_queue))
    await asyncio.gather(producer_task, consumer_task, timer_task)


if __name__ == "__main__":
    asyncio.run(main())
