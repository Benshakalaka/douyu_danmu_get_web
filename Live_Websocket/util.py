#encoding=utf-8
#+-------------------------------------------------------+
# wspy.util
# Copyright (c) 2015 OshynSong<dualyangsong@gmail.com>
#
# Construct socket connection pool
#+-------------------------------------------------------+
import sys
import os
import socket
import re
import uuid
import json
from hashlib import sha1, md5
import time
import heapq
from error import *
from enum import Enum

#用于select的可读
class SocketPool(list):
    '''All of the connected socket array'''
    def __init__(self, li=[]):
        super(SocketPool, self).__init__(li)

#用于每个客户连接
class Client(object):
    '''The client connection, identified by uuid'''
    def __init__(self, sock, timeout=30, handshake=False):
        if sock == None:
            raise NetworkError('Client socket is None!')
        if not isinstance(timeout, int) or timeout <= 0:
            raise WSTypeError('Timeout value or type is invalid!')
        uid = str(uuid.uuid1())
        uid = uid.split('-')
        uid = ''.join(uid)
        uid = uid.encode('utf-8')
        self.Uid      = sha1(uid).hexdigest()
        self.Sock     = sock
        self.Timeout  = timeout
        self.Handshake= handshake
        self.url = ''


#客户连接池
class ClientPool(dict):
    '''Client connection pool maintance by the server'''
    def __setattr__(self, uuid, cli):
        self[uuid] = cli

    def __getattr__(self, uuid):
        if self.has_key(uuid) and self[uuid] != None:
            return self[uuid]
        else: return None

#ws server父类
class WSSocket(object):
    '''The client connection socket class
    Each client connection has a uid for identification
    and a timeout for remove from the pool.
    '''
    def __init__(self, addr, port):
        #所有
        self.Sockets = SocketPool()
        #客户端
        self.Clients = ClientPool()
        #后端
        self.Backends = SocketPool()
        if isinstance(addr, str):
            if addr == 'localhost':
                pass
            else:
                a = re.match(r'([0-9]{1,3}\.){3}[0-9]{1,3}', addr)
                if a.group() == addr: pass
                else: raise WSError('Not valid address')
        else: raise WSTypeError('Address type error.')
        if isinstance(port, int):
            if port > 1024 and port < 65536: pass
            else: raise WSError('Not valid port.')
        else: raise WSTypeError('Port type error.')
        self.Host = self.__createHost((str(addr), int(port)))
        self.Sockets.append(self.Host)

    def __createHost(self, ap):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(ap)
        sock.listen(100)
        return sock

class BackendData(object):
    def __init__(self, type, url, peopleMax = -1):
        self.data = {}
        self.data['type'] = type
        self.data['url'] = url
        if peopleMax != -1:
            self.data['peopleMax'] = peopleMax

    def getMsg2Send(self):
        string = json.dumps(self.data)
        string_final = string.encode()
        return string_final

#每个backend server
class Backend(object):
    def __init__(self, backendName, port, addr='127.0.0.1'):
        #后端名字, 必须是douyu, longzhu, panda这样，在url中一定存在的单词，用于判断指定url属于哪个backend
        self.__backendName = backendName
        #默认本地
        self.__addr = addr
        #后端监听端口
        self.__port = port
        #后端对应的socket
        self.__sock = None
        #后端对应的客户池（不同于WSSocket中的客户池，这里的key为url, value为列表，其中为客户）
        #形式如下： {url1:[cli1, cli2], url2:[cli3, cli4]}
        self.Clients = ClientPool()
        #日志
        self.log = Log(backendName + '_backend')

    def initBackend(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect((self.__addr, self.__port))
        except:
            sock.close()
            sock = None
            self.log.write('failed to connect backend')
        self.__sock = sock
        return sock

    #判断某个url是否属于这个backend
    def isBelongHere(self, url):
        return self.__backendName in url

    #将某个客户添加到自己客户池里, 这里是Client对象
    #如果url本身已经存在，说明该房间正在被监听，只要加入client即可，不然要发信息过去让他马上监听
    def appendClient(self, url, client):
        if url not in self.Clients:
            #发送数据到后端？？？？？？？？？？？？？？？？？？？？？？？？？？？？？
            data = BackendData(1, url)
            self.__sock.send(data.getMsg2Send())
            self.Clients[url] = []

        self.Clients[url].append(client)

    #如果房间监听客户端就这一个人，删掉后就要向后端发送disconnect信息
    def deleteClient(self, url, client, peopleMax=10):
        if url not in self.Clients:
            self.log.write('this url %s not exist in %s backend' % (url, self.__backendName))
            return False

        for index,cli in enumerate(self.Clients[url]):
            if cli == client:
                del self.Clients[url][index]
                if len(self.Clients[url]) == 0:
                    del self.Clients[url]
                    data = BackendData(0, url, peopleMax)
                    self.__sock.send(data.getMsg2Send())
                return True

        return False

    def isThisSock(self, sock):
        return sock == self.__sock



#backend server pool
class BackendPool(list):
    def __init__(self, li=[]):
        super(BackendPool, self).__init__(li)

    def backendsInit(self):
        sockets = []
        for bk in self:
            sock = bk.initBackend()
            sockets.append(sock)
        return sockets

    def appendBackend(self, backend):
        self.append(backend)

    #加入的room url, 谁要加入, 发送后端的数据（可以直接从网页传过来就不重复构造了）
    def appendCli(self, url, client):
        for bk in self:
            if bk.isBelongHere(url):
                bk.appendClient(url, client)
                return True
        return False

    #取消加入的room url, 谁要取消, 发送后端的数据
    def deleteCli(self, url, client):
        for bk in self:
            if bk.isBelongHere(url):
                return bk.deleteClient(url, client)

        return False

    def getBackend(self, sock):
        for bk in self:
            if bk.isThisSock(sock):
                return bk

        return None


#小型日志系统
class Log(object):
    #level 0: 直接输出(默认)
    #level 1或其他: 输出至文件，后面需要跟文件名
    #日志级别：
    #WARNING: 警告，没有错误，能继续运行
    #ERROR:   错误，但能继续运行
    #FATAL:   错误，程序退出
    def __init__(self, LogName, method=0, filename='', infoType=('DEBUG', 'ERROR', 'FATAL')):
        if method != 0 and filename == '':
            exit('Usage : Log() or Log(1, filename) ...')
        elif filename != '':
            try:
                f = open(filename, 'w')
                self.__file = f
            except:
                exit('Wrong file name!')
        self.__method = method
        self.__infoLevel = infoType
        self.__name = LogName

    def write(self, msg, level=0):
        # timeStr = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        # finalStr = ('%s\n%s %s    %s') % (self.__name ,timeStr, self.__infoLevel[level], msg)
        #下面是不需要时间戳
        finalStr = ('%s : %s    %s') % (self.__name , self.__infoLevel[level], msg)
        if self.__method == 0:
            print(finalStr)
        else:
            self.__file.write(finalStr+'\n')

    def close(self):
        if self.__method != 0:
            self.__file.close()

#定时器
class Timer(object):
    def __init__(self):
        self.log = Log('Timer')
        self.heap = []

    def addTimer(self, danmu_sock, timeout_intern, current_time, absolute=False):
        if absolute == True:
            timeout = timeout_intern
        else:
            currTime = current_time
            timeout = currTime + timeout_intern
        heapq.heappush(self.heap, (timeout, danmu_sock))
        self.log.write(danmu_sock.url + ' has joined successfully')

    def delTimer(self, danmu_sock, current_time):
        #已超时的也不处理,实质上就是list，所以可以list遍历
        for index,ds in enumerate(self.heap):
            if ds[1] == danmu_sock:
                del self.heap[index]
                self.log.write('delete %s success' % danmu_sock.url)
                return True
        return False

    def getPopTopTimer(self):
        timer = None
        try:
            timer = heapq.heappop(self.heap)
        except:
            pass
        return timer

    #已超时返回true , 否则返回false
    def isTopTimeOut(self, current_time):
        if self.isEmptyTimer():
            return False
        #下面一句话有点难理解，，
        #return self.heap[0][0] < current_time
        if self.heap[0][0] <= current_time:
            return True
        else:
            return False

    def isEmptyTimer(self):
        return True if len(self.heap)==0 else False


if __name__ == '__main__':
    pass
