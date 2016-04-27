import os
import sys
import socket, select
import time
import json
import struct
import re
import base64
from hashlib import sha1, md5
from util import *

IOTYPE = ['select', 'pool', 'async']

class MS(WSSocket):

    def __init__(self, addr, port, ioType = 'select'):
        #本地初始化
        if ioType not in IOTYPE:
            raise WSTypeError('IO type not valid.')
        self.IO = ioType
        self.log = Log('MS')
        super(MS, self).__init__(addr, port)
        #后端初始化,其实可以用配置文件
        self.backendPool = BackendPool()
        self.backendPool.appendBackend(Backend('douyu', 8666))
        sockets = self.backendPool.backendsInit()
        # 现在有两种socket正在监听，本地ws服务端监听，backend客户端监听
        self.Backends.extend(sockets)
        self.Sockets.extend(sockets)

    def run(self):
        print('start...')
        while True:
            rs, ws, es = select.select(self.Sockets, [], [])
            for r in rs:
                #客户端连接进来
                if r == self.Host:
                    cliSock, addr = self.Host.accept()
                    if not cliSock:
                        self.log.write('Socket accept failed.')
                        continue
                    else:
                        self.connect(cliSock)
                elif r in self.Backends:
                    #获取后端数据，分发数据
                    backend = self.backendPool.getBackend(r)
                    content = r.recv(2048)
                    msgList = self.deal_with_recved_bytes(content)
                    for m in msgList:
                        self.extractMainContent(m, backend)
                else:
                    try:
                        data = r.recv(2048)
                        if len(data) == 0:
                            self.disConnect(r)
                        else:
                            cli = None
                            #为什么不通过fileno来进行key value呢？
                            for k,v in self.Clients.items():
                                if v.Sock == r:
                                    cli = v
                            if cli != None:
                                if not cli.Handshake:
                                    self.doHandShake(cli, data)
                                else:
                                    #接收客户发来的room dm request， 放到backend的客户池中
                                    self.process(cli, data)

                    except socket.error:
                        self.disConnect(r)
                        continue

    def pack(self, msg, first = 0x80, opcode = 0x01):
        firstByte  = first | opcode
        firstByte = firstByte
        encodeData = None
        #之前因为要在这里看msg，所以先变成了unicode,但现在要传输数据了，又要变回去
        msg = msg.encode('utf-8')

        #关于struct,可以看这个：http://www.cnblogs.com/gala/archive/2011/09/22/2184801.html
        cnt        = len(msg)
        if cnt >= 0 and cnt <= 125:
            encodeData = struct.pack('BB', firstByte, cnt) + msg
        elif cnt >= 126 and cnt <= 0xFFFF:
            #low  = cnt & 0x00FF
            #high = (cnt & 0xFF00) >> 8
            encodeData = struct.pack('>BBH', firstByte, 0x7E, cnt) + msg
        else:
            low  = cnt & 0x0000FFFF
            high = (cnt & 0xFFFF0000) >> 16
            encodeData = struct.pack('>BBLL', firstByte, 0x7F, high, low) + msg
        return encodeData

    def unpack(self, cliSock, msg):
        opcode = ord(msg[0:1]) & 0x0F
        mask   = (ord(msg[1:2]) & 0x80) >> 7
        pllen1 = ord(msg[1:2]) & 0x7F
        oriData    = ''
        maskKey    = ''

        #Close the connection or mask bit not set
        if opcode == 0x8:
            self.disConnect(cliSock)
            return None
        if mask != 1:
            raise UnmaskError('Mask bit is not set from client.')

        #Get mask key and original data
        if pllen1 >= 0 and pllen1 <= 125:
            maskKey = msg[2:6]
            oriData = msg[6:]
        elif pllen1 == 126:
            maskKey = msg[4:8]
            oriData = msg[8:]
        else:
            maskKey = msg[10:14]
            oriData = msg[14:]

        #Decode the masked original data
        l = len(oriData) ;
        decodeData = bytearray(l)
        for i in range(l):
            decodeData[i] = oriData[i] ^ maskKey[i % 4]

        #我们已经知道得到的依然是bytes类型的，所以想要print出来看看的话需要decode
        decodeData = decodeData.decode()
        return decodeData

    def send(self, cli, msg, isLast = True, opcode = 1):
        # self.say('> Send to client ' + cli.Uid + ':\n' + msg)
        if isLast: first = 0x80
        else: first = 0x00
        msg = self.pack(msg, first, opcode)
        cli.Sock.send(msg)

    def process(self, cli, data):
        data_json = self.unpack(cli.Sock, data)
        if data_json is None:
            return
        try:
            data = json.loads(data_json)
        except:
            self.log.write('data json loads error', 1)
            self.log.write(data_json)
        #1. 如果要连接房间，那么必须马上连接；但如果断开房间，则不立即断开，而是等待一段时间再断开或者是点击要连接另一个房间才断开(网页端处理)
        #2. 判断此房间是否正在被监听，正在的话就不必发送数据到backend, 否则需要发送(Backend类自动处理)
        #所以在这里ws server中就只是简单的转发信息
        if data['type'] == 1:
            cli.url = data['url']
            self.backendPool.appendCli(data['url'], cli)
        else:
            cli.url = ''
            self.backendPool.deleteCli(data['url'], cli)

    def getHeaders(self, data):
        resource = re.match(r'GET (.*?) HTTP', data)
        host     = re.search(r'Host: (.*?)\r\n', data)
        origin   = re.search(r'Origin: (.*?)\r\n', data)
        key      = re.search(r'Sec-WebSocket-Key: (.*?)\r\n', data)
        resource = resource.group(1) if resource != None else None
        host     = host.group(1) if host != None else None
        origin   = origin.group(1) if origin != None else None
        key      = key.group(1) if key != None else None
        return resource, host, origin, key

    def doHandShake(self, cli, data):
        #第一次浏览器和服务器交互，需要先握手确认信息
        #从socket中获取的信息，一般编码方式为utf-8，然而在python3内存中都是unicode编码，所以要处理的话就要先对utf-8解码，就成了unicode了
        data = data.decode('utf-8')
        resource, host, origin, key = self.getHeaders(data)
        self.log.write('Requesting handshake: %s ...' % host)
        #websocket version 13
        key = key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
        #这里的算法明确要求传入的必须是bytes类型的，于是就编码成utf-8的
        key = key.encode('utf-8')
        sha1Encrypt = sha1(key).digest()
        acceptKey   = base64.b64encode(sha1Encrypt)
        acceptKey = acceptKey.decode()
        self.log.write('Handshaking...')
        upgrade = 'HTTP/1.1 101 Switching Protocol\r\n' + \
                  'Upgrade: websocket\r\n' + \
                  'Connection: Upgrade\r\n' + \
                  'Sec-WebSocket-Accept: ' + acceptKey + \
                  '\r\n\r\n'
        #之前既然已经对utf-8解码了，在发送前要编码成utf-8的才行
        cli.Sock.send(upgrade.encode('utf-8'))
        cli.Handshake = True
        self.log.write('Handshake Done.')
        return True

    def connect(self, cliSock, timeout=30, handshake=False):
        cli = Client(cliSock, timeout, handshake)
        self.Clients[cli.Uid] = cli
        self.Sockets.append(cliSock)
        self.log.write(cli.Uid + ' CONNECTED!')

    def disConnect(self, cliSock):
        inSockets = -1
        inClients = ''
        for i,s in enumerate(self.Sockets):
            if s == cliSock:
                del self.Sockets[i]
                inSockets = i
                break
        for k,v in self.Clients.items():
            if v.Sock == cliSock:
                #还要从每个后端的客户池里删（虽然不一定有）
                #这种情况主要是因为在客户发来连接请求后，没有发送离开请求就断开连接了
                self.backendPool.deleteCli(self.Clients[k].url, self.Clients[k])
                del self.Clients[k]
                inClients = k
                break
        if inSockets != -1 and inClients != '':
            cliSock.close()
            self.log.write('Client socket %s Disconnected' % inClients)


    def deal_with_recved_bytes(self, content):
        msgList = []
        total_len = len(content)
        len_addressed = 0
        while True:
            try:
                len_prev = struct.unpack('i', content[0:4])[0]+4
            except:
                return []

            try:
                str_ret = content[12:len_prev-1].decode()
            except:
                str_ret = '这个有毒，decode出错'

            len_addressed += len_prev
            msgList.append(str_ret)

            if len_addressed == total_len:
                break

            content = content[len_prev:]
        return msgList

    def extractMainContent(self, msg, backend):
        data = eval(msg)
        for url,content_all in data['urlDict'].items():
            #这个content_all是个list啊！！
            content_all_2_send = json.dumps(content_all)
            #backend.distributeMessage(url, content_all_2_send_encode)
            for cli in backend.Clients[url]:
                self.send(cli, content_all_2_send)



if __name__ == '__main__':
    ms = MS('127.0.0.1', 5005)
    ms.run()
