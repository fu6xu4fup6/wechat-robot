#!/usr/bin/pypy3

#-*- coding: utf-8 -*-
import json
import sys
import struct
import socket

'''
auther: Hui
date: 2024.05.01
功能: 发送消息给消息队列
'''

HOST = "127.0.0.1"
PORT = 54321


def cal_checksum(data):
    # 计算校验和
    checksum = sum(data) & 0xFF
    return checksum

def pack_packet(json_data):
    pack_header = b'HEAD'
    data_len = len(json_data)
    checksum = cal_checksum(json_data)
    packet = pack_header + struct.pack('!I', data_len) + json_data + bytes([checksum])
    padding = b'\x00' * (1024 - len(packet))
    packet = packet + padding
    return packet

def pack_json(text,api_url):
    #组包
    webchat_json = {
     "msgtype": "markdown",
        "markdown": {
            "content": text
        }
    }
    pkg_json = {
            "url" : api_url,
            "data" : webchat_json
            }
    jsonData = json.dumps(pkg_json).encode('utf-8')
    return pack_packet(jsonData)

if __name__ == '__main__':
    subject = sys.argv[1]
    text = sys.argv[2]
    apiUrl = sys.argv[3]
    
    #备线不发报警
    if ("MPLS VPN备线" in text and "reboot" in text):
        sys.exit(0)
    elif (text.find("reboot") > -1) and (subject.find("告警") > -1):
        text = '<font color="comment">'+text+'</font>'
    elif (text.find("reboot") > -1) and (subject.find("恢复") > -1):
        sys.exit(0)
    elif subject.find("告警") > -1:
        text = '<font color="warning">'+text+'</font>'
    elif subject.find("恢复") > -1:
        text = '<font color="info">'+text+'</font>'


    packet = pack_json(text,apiUrl)
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_socket.sendto(packet, (HOST,PORT))
