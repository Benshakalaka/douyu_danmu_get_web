import struct
import time
import heapq
import re
import socket
import requests
import json
from enum import Enum
from hashlib import md5
from error import *
from urllib import parse
from collections import deque
import uuid
import math


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

#定时器，有待加工
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
            self.log.write('still %d timers' % len(self.heap))
        except:
            self.log.write('No timer exists! %d' % len(self.heap))
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
        return True if len(self.heap) == 0 else False

#当前连接的状态，分为尚未连接（只会出现一会儿，在对象创建和连接成功期间是这种）， 正在连接（正在传输弹幕）， 即将关闭（客户要求关闭，但我这里延迟关闭）
class DMSStatus(Enum):
    closed = 0
    connecting = 1
    closing = 2

#当前连接的超时事件类型， 心跳事件，关闭事件（有关闭事件正是因为延迟关闭才有的）
class DMTEventType(Enum):
    nothing = 0
    keepAlive = 1
    closing = 2

def getMd5Hex(string):
    md5_o = md5()
    md5_o.update(string)
    md5_str = md5_o.hexdigest()
    return md5_str

#分3种连接，一个是监听的，一个是ws那边的，另外n个是dm server那边的
#下面这个是dm server的
class DanmuSocket(object):
    def __init__(self, url, keepAliveIntern=40):
        #对应room的地址
        self.url = url
        #状态，一个是在关闭的状态，一个是正常有人想要这个的状态，一个是即将关闭状态
        #之所以要这个即将关闭的状态，是因为可能在关闭之后再次打开的几率比较高
        #关闭的状态是指创建这个对象后正在连接dm server但还没成功时
        self.status = DMSStatus.closed
        #要关闭的绝对时间,,,,,这里要考虑到ws server中途断开的问题！！！！
        self.closingTimeout = -1
        #延迟时间
        self.delayTimeout = -1
        #在dm连接池里的标志,这里我使用url的md5值来作为存在池中的key
        #因为要在之后用到，比如某个room即将断开，但又被需要，这时候就要先在dm pool里找一遍有没有
        #url作为key容易找
        #self.md5Mark = getMd5Hex(url)
        self.Mark = -1
        #对应的socket
        self.sock = None
        #操作对象，此对象能根据给定的url连接dm server等操作
        self.operation = Douyu_DanMuGet(url)
        #超时事件,这里有两种，一个是心跳事件，一个是即将关闭事件
        self.timeoutEventType = DMTEventType.nothing
        #绑定超时函数
        self.timeoutEvent = None
        #心跳间隔
        self.keepAliveIntern = keepAliveIntern

    def getDanmuServerSock(self):
        self.operation.get_verify_server_list()
        self.operation.get_username_gid()
        self.sock = self.operation.get_danmu_server_sock()
        self.Mark = self.sock.fileno()
        self.status = DMSStatus.connecting

    #既然这个对象被作为元素的一部分放到Timer里去了，又Timer是一个优先队列，所以该类的所有实例必须能进行比较
    #但是，我这里对于相同的时间谁先被处理并不介意，所以就随便指定元素比较了
    def __eq__(self, other):
        return self.Mark == other.Mark
    def __ge__(self, other):
        return self.Mark >= other.Mark
    def __gt__(self, other):
        return self.Mark > other.Mark
    def __le__(self, other):
        return self.Mark <= other.Mark
    def __lt__(self, other):
        return self.Mark < other.Mark


#dm连接池，就是一个字典
#这里我默认socket的fileno作为key，DanmuSocket作为value
class DanmuSocket_Pool(dict):
    def __setattr__(self, key, value):
        self[key] = value

    def __getattr__(self, item):
        if self.has_key(item) and self[item] != None:
            return self[item]
        else:
            return None

#这是所有连接，这个将来放在select系列函数里，就是个列表
class SocketPool(list):
    '''All of the connected socket array'''
    def __init__(self, li=[]):
        super(SocketPool, self).__init__(li)


#这里我只弄一个ws server了，如果要多个ws server的话，那么就要给个ws server pool，将来数据分发也要考虑，这里就不考虑了
class BaseServer(object):
    def __init__(self, addr, port):
        self.log = Log('BaseServer')
        #可读可写监听池
        self.inSockets = SocketPool()
        #可写里我只监听ws server, 虽然dm server 的心跳包也是out,但我感觉不至于要通过select来监听吧？
        self.outSockets = SocketPool()
        #这里心跳的时候要可写事件
        self.Danmus = DanmuSocket_Pool()
        #对应的ws servre，只支持一个
        #什么时候可写呢？
        self.ws_sock = None
        self.ws_sock_writeEvent = False
        self.ws_sock_isWriteLeft = False
        self.ws_sock_writeLeft = ''
        #一个定时器
        self.mainTimer = Timer()

        if isinstance(addr, str):
            if addr == 'localhost':
                pass
            else:
                a = re.match(r'([0-9]{1,3}\.){3}[0-9]{1,3}', addr)
                if a.group() == addr: pass
                else: raise WSError('Not valid address')
        else:
            raise WSTypeError('Address type error.')
        if isinstance(port, int):
            if port > 1024 and port < 65536: pass
            else: raise WSError('Not valid port.')
        else: raise WSTypeError('Port type error.')
        self.Host = self.__createHost((str(addr), int(port)))
        self.inSockets.append(self.Host)

    def __createHost(self, ap):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(ap)
        sock.listen(100)
        return sock



#斗鱼的每条消息都有格式，且格式是统一的，所以封装起来
class message(object):
    #参数为传输的内容
    def __init__(self, content):
        #协议格式： 长度 + 未知（重复长度）+ 未知（固定） + content + end
        self.dateLen = len(content) + 9
        self.dateLenRepeat = self.dateLen
        self.magicCode = 0x2b1
        self.content = content
        self.end = 0x0

    def getMsg(self):
        str2send = struct.pack('iii', self.dateLen, self.dateLenRepeat, self.magicCode) + self.content.encode('utf-8') + struct.pack('b', self.end)
        return str2send



#获取弹幕的
class Douyu_DanMuGet(object):
    def __init__(self, url, logMethod=0, logFilename=''):
        self.url = url
        self.log = Log('Douyu_DanMuGet', logMethod, logFilename)

    def uuid_str(self):
        #本身uuid产生的字符串是 xxx-xxx-xxx的，这里处理成 xxxxxxx样子的
        uuidStrInit = str(uuid.uuid1())
        uuid_list = uuidStrInit.split('-')
        uuidStr = ''.join(uuid_list)
        return uuidStr

    def msg_loginreq(self):
        #房间id
        roomid = self.roomId
        #设备id，这里用uuid产生，比较随意
        devid = self.uuid_str()
        #时间戳
        rt = str(int(time.time()))

        #这个看别人的
        vk_str = rt + '7oE9nPEG9xXV69phU31FYCLUagKeYtsF' + devid
        vk_need_md5 = vk_str.encode()
        m = md5()
        m.update(vk_need_md5)
        vk = m.hexdigest()

        content = 'type@=loginreq/username@=/ct@=0/password@=/roomid@='+str(roomid)+'/devid@='+devid+'/rt@='+rt+'/vk@='+vk+'/ver@=20150929/'
        return content

    #获取认证服务器列表（每次打开某个主播页面好像都不一样，会变）
    def get_verify_server_list(self):
        #得到整个网页
        wholePage = requests.get(self.url)

        #获取两个变量
        roomInfo = ''
        roomArgs = ''
        infoNeeded = re.search(r'\$ROOM = (.*?);\r.*?\$ROOM.args = (.*?);\r', wholePage.text, re.S)
        if infoNeeded is None:
            self.log.write('Not found roomInfo or roomArgs', 2)
            exit(-1)
        else:
            roomInfo = infoNeeded.group(1)
            roomArgs = infoNeeded.group(2)
            self.log.write('roomInfo : ' + roomInfo)
            self.log.write('roomArgs : ' + roomArgs)

        #因为格式与json一样的字符串，我用json来解析
        #这样第一步就是获取到了这两个变量
        self.roomInfo = json.loads(roomInfo)
        self.roomArgs = json.loads(roomArgs)

        #获取roomid
        #除了roomid这个信息之外，这里面可能还有一个主播当前是否在直播的字段有价值
        #字段名为show_status， 为1表示在直播，为2表示当前不在直播
        self.roomId = self.roomInfo['room_id']

        #获取认证服务器地址
        servers_address_list_str = parse.unquote(self.roomArgs['server_config'])
        self.servers_address_list = json.loads(servers_address_list_str)
        self.log.write(str(self.servers_address_list))

    #这里的server_list必须是[{'ip': 'xxx.xxx.xxx.xxx', 'port': 'xxxx'}, {'ip': 'xxx.xxx.xxx.xxx', 'port': 'xxxx'}, {'ip': 'xxx.xxx.xxx.xxx', 'port': 'xxxx'}]
    def connect_2_server(self, server_list):
        chosen_server_index = 0
        while True:
            if chosen_server_index == -1 or chosen_server_index == len(server_list):
                break
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            ipaddr_port = (server_list[chosen_server_index]['ip'], int(server_list[chosen_server_index]['port']))
            try:
                #connect里的是一组tuple, ipaddr(str) + port(int)
                sock.connect(ipaddr_port)
                chosen_server_index = -1
            except:
                sock.close()
                chosen_server_index += 1
                sock = None
        return sock

    #因为粘包问题，要循环处理一段接收到的bytes,返回这段bytes中的消息列表
    def deal_with_recved_bytes_main(self, content):
        # content_cp = content
        # try:
        #     msgList = []
        #     total_len = len(content)
        #     len_addressed = 0
        #     while True:
        #         len_prev = struct.unpack('i', content[0:4])[0]+4
        #         str_ret = content[12:len_prev].decode()
        #         len_addressed += len_prev
        #         msgList.append(str_ret)
        #
        #         if len_addressed == total_len:
        #             break
        #
        #         content = content[len_prev:]
        #     return msgList
        # except:
        #     self.log.write('unpack or decode error...')
        #     self.log.write(content_cp)
        #     return []

        #在新增加了数据流缓冲区(BytesBuffer)后，这个处理方法就可以简化了
        try:
            len_content = len(content)
            str_ret = content[12:len_content-1].decode()
            return str_ret
        except:
            self.log.write('content decode error------')
            self.log.write(content)
            return None

    #上面不是说这个函数已经被抛弃了吗？。。。哦好吧，因为这个函数用在弹幕服务器连接上没出现过问题，那里又不想改了，所以放着吧。。。
    #所以上面的函数改个名字，放到server.py里作为主要用的那个处理函数
    def deal_with_recved_bytes(self, content):
        content_cp = content
        try:
            msgList = []
            total_len = len(content)
            len_addressed = 0
            while True:
                len_prev = struct.unpack('i', content[0:4])[0]+4
                str_ret = content[12:len_prev].decode()
                len_addressed += len_prev
                msgList.append(str_ret)

                if len_addressed == total_len:
                    break

                content = content[len_prev:]
            return msgList
        except:
            self.log.write('unpack or decode error...')
            self.log.write(content_cp)
            return []

    #获取在弹幕服务器中的用户名和所在组id
    def get_username_gid(self):
        content = self.msg_loginreq()
        #尚未编码
        msg2send = message(content)

        #连接认证服务器
        self.verify_sock = self.connect_2_server(self.servers_address_list)
        if self.verify_sock == None:
            self.log.write('Failed to connect verify server!', 2)
            exit(-1)

        #向认证服务器发送消息
        self.verify_sock.send(msg2send.getMsg())

        #下面是接收数据，可以加入select或是多线程，但这里不用
        #因为这里就为了获取两个数据username和gid
        #且只要接收两段数据
        #当然，在第二段数据里好几段msg， gid那段在后面，虽然第一段我们不在意，但是在第一段里有弹幕服务器地址及端口，不关注是因为别人搞出来了，且这是不变的所以不再关注
        self.username = ''
        self.gid = ''
        for i in range(2):
            content_recv = self.verify_sock.recv(1024)
            msgList = self.deal_with_recved_bytes(content_recv)
            for respond in msgList:
                if self.username == '':
                    username_re = re.search(r'username@=(.*?)/', respond)
                    if username_re is not None:
                        self.username = username_re.group(1)

                if self.gid == '':
                    gid_re = re.search(r'gid@=(.*?)/', respond)
                    if gid_re is not None:
                        self.gid = gid_re.group(1)

        if self.username == '' or self.gid == '':
            self.log.write('username or gid is null !', 2)
            exit(-1)
        self.verify_sock.close()

        self.log.write('username : ' + self.username + ' and gid : ' + self.gid)

    #连接至弹幕服务器，并发送认证信息
    def get_danmu_server_sock(self):
        #发给弹幕服务器的信息就不像认证的那么多那么繁琐了，所以就不单独立一个函数出来了
        content = "type@=loginreq/username@=" + self.username + "/password@=1234567890123456/roomid@=" + str(self.roomId) + "/"
        msg2send = message(content)

        #构建danmu_server_list，这个是不变的
        portList = [8061, 8062, 12601, 12602]
        danmu_server_list = []
        for portNum in portList:
            ip_port = {}
            ip_port['ip'] = 'danmu.douyutv.com'
            ip_port['port'] = portNum
            danmu_server_list.append(ip_port)

        self.danmu_server_sock = self.connect_2_server(danmu_server_list)
        self.danmu_server_sock.send(msg2send.getMsg())

        content = "type@=joingroup/rid@=" + str(self.roomId) + "/gid@="+self.gid+"/"
        msg2send = message(content)
        self.danmu_server_sock.send(msg2send.getMsg())

        return self.danmu_server_sock


    # def danmu_get(self):
    #     while True:
    #         content_recv = self.danmu_server_sock.recv(1024)
    #         msgList = self.deal_with_recved_bytes(content_recv)
    #         for msg in msgList:
    #             print(msg)

    #心跳包
    def keep_alive_package(self):
        content = "type@=mrkl/"
        msg2send = message(content)
        self.danmu_server_sock.send(msg2send.getMsg())

    #整个流程
    # def run(self):
    #     self.get_verify_server_list()
    #     self.get_username_gid()
    #     self.get_danmu_server_sock()
    #
    #     self.log.write('弹幕接收开始...')
    #     recv_socks = []
    #     recv_socks.append(self.danmu_server_sock)
    #     timeout = 40
    #     timeout_absolute = 40 + int(time.time())
    #     while True:
    #         rs, ws, es = select.select(recv_socks, [], [], timeout)
    #
    #         for s in rs:
    #             if s == self.danmu_server_sock:
    #                 content_recv = self.danmu_server_sock.recv(1024)
    #                 msgList = self.deal_with_recved_bytes(content_recv)
    #                 for msg in msgList:
    #                     u,c = self.extractMainContent(msg)
    #                     print(u + ':' + c)
    #
    #         time.sleep(5)
    #         currentTimeSec = int(time.time())
    #         if currentTimeSec > timeout_absolute:
    #             self.keep_alive_package()
    #             timeout_absolute = 40 + currentTimeSec

    #数据像下面这样
    #type@=chatmsg/rid@=7911/uid@=3949372/nn@=温暖冬天/txt@=即使再有第二个科比，也没有青春去追随。/cid@=b0d294e9926f43e020b4310000000000/level@=2/
    #type@=chatmsg/rid@=7911/uid@=13632978/nn@=panwen205/txt@=厉害/cid@=b0d294e9926f43e021b4310000000000/level@=4/ct@=2/
    #type@=chatmsg/rid@=7911/uid@=5708144/nn@=君殇sn/txt@=韦神求网易云ID，求歌单5/cid@=b0d294e9926f43e026b4310000000000/level@=3/
    #我要取用户名和说的话
    def extractMainContent(self, msg):
        msg_list = msg.split('/')

        if len(msg_list) < 5:
            return None

        typeStr = msg_list[0]
        typeData = typeStr.split('=')[1]
        #还有gift, ranklist等类型消息被我在这里去掉了
        if typeData != 'chatmsg':
            return None

        usernameStr = msg_list[3]
        contentStr = msg_list[4]

        username = usernameStr.split('=')[1]
        content = contentStr.split('=')[1]

        return username, content


#将要发送到ws server的消息缓冲区
class MessageListBuffer(object):
    def __init__(self, totalMax, singleMax):
        self.__totalMax = totalMax
        self.__singleMax = singleMax
        self.__log = Log('MessageListBuffer')
        #这字典里的value是deque类型， key是url字符串
        self.__dic = dict()

    def appendItem(self, url, type, username, message):
        if self.lengthItem() >= self.__totalMax:
            self.__log.write('too many messages in buffer !', 1)
            return
        #这里的type是指消息类型，可能是礼物啊什么的
        content = '@type=' + str(type) + '/@username=' + username + '/@msg=' + message
        if url in self.__dic:
            if len(self.__dic[url]) >= self.__singleMax:
                self.__log.write('too many for this room:'+url, 1)
            else:
                self.__dic[url].append(content)
        else:
            self.__dic[url] = deque()
            self.__dic[url].append(content)

    #之所以要用dict的方式来存消息，是我不想某个room的dm突然占据所有空间
    #下面取出消息就是去每个房间取n个消息
    def getPopItem(self):
        if self.lengthItem() == 0:
            return {}
        #返回的msgBox形式是：
        #{'urlCount':len, 'urlDict':{url1:[], url2:[]...}}
        msgBox = {}
        urlCount = 0
        msgBox['urlDict'] = {}
        #最多获取每个房间的dm数量
        maxGetLen = 15
        #这里的__dic形式是：
        #{url1:deque, url2:deque}
        for u,m in self.__dic.items():
            if len(m) == 0:
                continue
            urlMsgBox = []
            getLen = len(m) if len(m) < maxGetLen else maxGetLen
            #msgBox.extend((list(m))[0:getLen])
            for i in range(getLen):
                urlCount += 1
                urlMsgBox.append(m.popleft())
            msgBox['urlDict'][u] = urlMsgBox
        msgBox['urlCount'] = urlCount
        return msgBox

    def lengthItem(self):
        # print(str(len(self))+'...')
        if len(self.__dic) == 0:
            return 0

        length = 0
        for k, v in self.__dic.items():
            length += len(v)

        return length

    def hasKey(self, url):
        return url in self.__dic

    def deleteItem(self, url):
        if self.hasKey(url):
            del self.__dic[url]
            return True
        else:
            return False


#每个连接都需要一个对应的字节流缓冲区，所以这里我就使用字典形式： {sock1:[bytes], sock2:[bytes],...}
class BytesBuffer(dict):
    #key为套接字文件描述符，value即为二进制字符串形式(b''这样，所以这里我使用bytearray)
    #但是注意传给构造函数的必须是DanmuSocket类型哦!!!!
    def __setattr__(self, sock, bytesBuffer):
        self[sock.Mark] = bytesBuffer

    def __getattr__(self, sock):
        if self.has_key(sock.Mark) and self[sock.Mark] != None:
            return self[sock.Mark]
        else:
            return None

    #单纯的添加数据，不做其他事
    def appendData(self, sock, bytesContent):
        fn = sock.Mark
        if fn not in self:
            self[fn] = bytearray()

        self[fn].extend(bytesContent)

    #单纯的移除数据，不做其他事
    def removeData(self, sock, len):
        fn = sock.Mark
        if fn not in self:
            return False

        self[fn] = self[fn][len:]

    #返回当前某个连接buffer流中[完整的消息]的列表
    #一个完整的消息包含两部分，消息长度+消息体
    def getFullMsgList(self, sock):
        fn = sock.Mark

        msgList = []

        while True:
            currBufferLen = self.lengthOfBuffer(sock)
            #消息长度占4个字节
            if currBufferLen < 4:
                return msgList

            #包体长度
            msgLen = struct.unpack('i', self[fn][0:4])[0]
            #整个包长度（包长 + 包体长）
            msgFullLen = msgLen + 4

            #不够一个完整的包，不再继续解析
            if currBufferLen < msgFullLen:
                return msgList
            else:
                msgList.append(self[fn][0:msgFullLen])
                self.removeData(sock, msgFullLen)

    #返回某个连接的buffer池中二进制数据长度
    def lengthOfBuffer(self, sock):
        return len(self[sock.Mark])


if __name__ == '__main__':
    mb = MessageListBuffer(100,10)
    mb.appendItem('aaaaa', 1, 'aaa', 'bbb')
    mb.appendItem('aaaaa', 1, 'aaa', 'bbb')
    mb.appendItem('aaaaaccc', 1, 'aaa', 'bbb')
    print(mb.lengthItem())














