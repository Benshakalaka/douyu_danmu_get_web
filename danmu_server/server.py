import socket
import json
import select
from util_m import *

class Server(BaseServer):
    def __init__(self, addr, port):
        super(Server, self).__init__(addr, port)
        self.log = Log('Server')
        self.messageListBuffer = MessageListBuffer(400, 50)
        self.bytesListBuffer = BytesBuffer()

    def run(self):
        #timeout还没有处理
        print('start ...')
        #每1秒select都会强制返回一次，用于处理可能的超时事件
        time_out_used_in_select = 1
        while True:
            rs, ws, es = select.select(self.inSockets, self.outSockets, [], time_out_used_in_select)
            #一次循环里必须使用同一个时间戳
            current_time = int(time.time())
            for r in rs:
                #像这个监听端口建立连接只能是ws server
                #像我这里只能有一个ws server  暂时不考虑扩展
                if r == self.Host:
                    ws_sock, address = self.Host.accept()
                    #没有采用非阻塞，疏忽了，是一个败笔...
                    if not ws_sock:
                        self.log.write('Socket accept failed.')
                        continue
                    self.ws_sock = ws_sock
                    self.inSockets.append(ws_sock)
                    self.log.write(str(address) + ' ws server connected !')
                #ws server发过来请求某个room的dm或者不再要某个room了
                #数据格式是: type + 人数(douyu room 人数，不是我这个网页上的人数,单位是万, 整型) + url
                #在请求room时人数为0， 在取消room时人数用于决定该房间没人需要时多久后关闭
                #type分为0和1,0为取消，1为需要
                #传输方式为json
                elif r == self.ws_sock:
                    ws_data_str = self.ws_sock.recv(1024)
                    if len(ws_data_str) == 0:
                        #断开连接
                        for i,s in enumerate(self.inSockets):
                            if s == self.ws_sock:
                                self.ws_sock.close()
                                del self.inSockets[i]
                                break
                        self.log.write('ws server disconencted')
                        continue
                    ws_data_str =ws_data_str.decode()
                    ws_data = json.loads(ws_data_str)
                    self.log.write('from ws server : ' + str(ws_data))
                    url_aim = ws_data['url']
                    if ws_data['type'] == 1:
                        #建立房间dm server的连接
                        self.room_dm_connect(url_aim, current_time)
                    else:
                        #如果是取消的话，room的接收状态可能是关闭或者即将关闭
                        self.room_dm_disconnect(url_aim, ws_data['peopleMax'], current_time)
                #dm server发过来的dm
                else:
                    #处理二进制流，给了个二进制buffer，因为可能接收的数据不完整等，整理出完整的数据再进行处理
                    roomDm = self.Danmus[r.fileno()]
                    roomUrl = roomDm.url
                    dm_data_str = r.recv(1024)
                    self.bytesListBuffer.appendData(roomDm, dm_data_str)
                    #如果room dm server的dm不被需要，那么接收到后直接丢弃
                    # if roomDm.status == DMSStatus.connecting:
                    #     roomUrl = roomDm.url
                    #     msgList = roomDm.operation.deal_with_recved_bytes(dm_data_str)
                    #     for msg in msgList:
                    #         u,c = roomDm.operation.extractMainContent(msg)
                    #         self.log.write(u + ':' + c)
                    #         self.messageListBuffer.appendItem(roomUrl, 1, u, c)
                    dm_data_str_list = self.bytesListBuffer.getFullMsgList(roomDm)
                    for dm_data in dm_data_str_list:
                        msg = roomDm.operation.deal_with_recved_bytes_main(dm_data)
                        if msg is None:
                            continue
                        ret = roomDm.operation.extractMainContent(msg)
                        if ret is not None:
                            u = ret[0]
                            c = ret[1]
                            self.log.write('-------------' + u + ':' + c)
                            #之所以要len(u)!=1,是为了去掉礼物信息,具体礼物返回的消息我没仔细去看
                            #输出会有句 火箭:1, 这种是因为有人送了火箭礼物
                            if roomDm.status == DMSStatus.connecting and len(u) != 1:
                                self.messageListBuffer.appendItem(roomUrl, 1, u, c)
                        else:
                            self.log.write('extractMainContent not return username and content.......', 1)

            #就是说没有数据进来，之前的也全部取出来（不代表发完）了，那么就不需要触发ws server的写事件了
            #但是要注意的是，可能上一次取出了所有数据，但没有发完，就会在下面的for循环里继续发送，如果仍然没有发送完全，那么也会覆盖这里的writeEvent值，继续监听写事件
            if self.messageListBuffer.lengthItem() == 0:
                self.ws_sock_writeEvent = False
            else:
                self.ws_sock_writeEvent = True

            for w in ws:
                #要知道，这里发送给ws server可能发送不完全，就要考虑接着发送
                #还要考虑到message buffer中有还有数据要发送的问题
                #所以这里就涉及到粘包，包体不完全问题了
                #设计一个简单的协议判断包体的完整性
                #借用douyu 的包体协议
                #协议格式： 长度 + 未知（重复长度）+ 未知（固定） + content + end
                #这样也好把之前处理的一套拿过来直接用
                #这么一来就要去修缮message类
                #content是json字符串
                if w == self.ws_sock:
                    #如果上一次没有写完,这一次继续写，如果能写完，就继续写新内容
                    #如果不能写完，就不再继续写新内容
                    if self.ws_sock_isWriteLeft == True:
                        # self.log.write('send to ws server old data')
                        toSentLen = len(self.ws_sock_writeLeft)
                        sentDataLen = self.ws_sock.send(self.ws_sock_writeLeft)
                        if sentDataLen >= toSentLen:
                            self.ws_sock_isWriteLeft = False
                            self.ws_sock_writeLeft = ''
                        else:
                            self.ws_sock_writeLeft = self.ws_sock_writeLeft[sentDataLen:]

                    #如果之前发送的仍有遗留，说明还没发送完，这里更不能发送了
                    #如果之前没有遗留或者就算有也已经发送完了，就可以开始新内容的发送
                    if self.ws_sock_isWriteLeft == False:
                        #也有可能是因为遗留数据导致的对写事件感兴趣
                        if self.messageListBuffer.lengthItem() > 0:
                            # self.log.write('send to ws server new data')
                            #self.log.write('message buffer has------------- %d -------------datas' % self.messageListBuffer.lengthItem())
                            toSendMessage_dic = self.messageListBuffer.getPopItem()
                            toSendMessage_str = json.dumps(toSendMessage_dic)
                            tSM = message(toSendMessage_str)
                            #得到的字符串是经过编码的，可直接发送
                            tSM_final = tSM.getMsg()
                            tSM_final_len = len(tSM_final)
                            sentDataLen = self.ws_sock.send(tSM_final)
                            if sentDataLen < tSM_final_len:
                                self.log.write('send to ws server not end')
                                self.ws_sock_isWriteLeft = True
                                self.ws_sock_writeLeft = tSM_final[sentDataLen:]

                    #对写事件感兴趣主要是因为两个原因，一个是因为数据发送有遗留，一个是有新数据需要发送
                    if self.ws_sock_writeLeft == True or self.messageListBuffer.lengthItem() != 0:
                        self.ws_sock_writeEvent = True

            if self.ws_sock_writeEvent == False:
                if len(self.outSockets) != 0:
                    self.outSockets.clear()
            else:
                if len(self.outSockets) == 0:
                    self.outSockets.append(self.ws_sock)

            self.timeout_process(current_time)

    #通过url得到roomDm(DanmuSocket)
    def url2roomDm(self, url):
        roomDm = None
        for mk, rD in self.Danmus.items():
            if rD.url == url:
                roomDm = rD
                break
        return roomDm

    def room_dm_connect(self, url, current_time):
        roomDm = self.url2roomDm(url)
        #当前这个room不连接着
        if roomDm is None:
            self.log.write('new room is connecting...')
            #连接到dm server
            roomDm = DanmuSocket(url)
            roomDm.getDanmuServerSock()

            #用于判断该room是否已经在被监听
            if roomDm.Mark not in self.Danmus:
                self.Danmus[roomDm.Mark] = roomDm

            #用于传递给select的参数
            if roomDm.sock not in self.inSockets:
                self.inSockets.append(roomDm.sock)

            #加入心跳超时事件
            roomDm.timeoutEventType = DMTEventType.keepAlive
            roomDm.timeoutEvent = self.keep_alive_event

            self.mainTimer.addTimer(roomDm, roomDm.keepAliveIntern, current_time)

        #当前房间正在即将断开的状态又来说这个房间的dm是被需要的怎么处理呢？
        else:
            if roomDm.status == DMSStatus.connecting:
                self.log.write('ws server is wrong ? repeat request...', 1)
            elif roomDm.status == DMSStatus.closing:
                #也就是说，下面马上会触发关闭room的事件，那我就提前执行关闭函数，之后重新连接
                if roomDm.closingTimeout < current_time:
                    self.log.write('the closing room will restart ...')
                    #真正断开
                    self.room_dm_close(roomDm, current_time)
                    #重连,状态什么的应该都不需要改动等
                    self.room_dm_connect(url, current_time)
                else:
                    self.log.write('the closing room will recover ...')
                    #暂时还不会立即关闭room，也就是说又要分情况，下一次超时事件是心跳还是关闭
                    #如果是心跳，那么很简单,改了之后谁也不会察觉
                    if roomDm.timeoutEventType == DMTEventType.keepAlive:
                        roomDm.status = DMSStatus.connecting
                        roomDm.closingTimeout = -1
                        roomDm.delayTimeout = -1
                    #但如果是关闭的话，获取到超时延迟时间，获取到超时绝对时间，获取到当前时间，就可以知道距离上一次心跳的时间
                    #因为关闭事件都是从心跳事件出来的，可以这样也是因为我把延迟时间的单位作为心跳时间的缘故
                    else:
                        #获取上一次心跳的时间
                        lastKeepAlive = roomDm.closingTimeout - roomDm.delayTimeout
                        #获取距离上一次心跳已经pass的时间
                        passedTime = current_time - lastKeepAlive
                        #获取下一次心跳的间隔
                        nextKeepAlive = roomDm.keepAliveIntern - passedTime
                        #加入定时器
                        self.mainTimer.addTimer(roomDm, nextKeepAlive, current_time)
                        #修改状态
                        roomDm.timeoutEventType = DMTEventType.keepAlive
                        roomDm.status = DMSStatus.connecting
                        roomDm.timeoutEvent = self.keep_alive_event
                        roomDm.closingTimeout = -1
                        roomDm.delayTimeout = -1


    #延迟关闭
    def room_dm_disconnect(self, url, peopleMax, current_time):
        #根据url获取到对应的DanmuSocket对象
        roomDm = self.url2roomDm(url)
        if roomDm is None:
            self.log.write('cannot find aim url in Dm pool', 2)
            exit(-1)
        #计算出延时关闭时间(单位是心跳次数，40秒一次, 限制最长维持10分钟600秒15次心跳，预估一下人数最多150W; 最少维持1次心跳),更改状态
        #也就是10以及10以下一次心跳，递增，最多15次
        nkeepAlive = int(peopleMax / 10)
        if nkeepAlive < 1: nkeepAlive = 1
        if nkeepAlive > 15: nkeepAlive = 15
        roomDm.delayTimeout = nkeepAlive * roomDm.keepAliveIntern
        roomDm.closingTimeout = current_time + roomDm.delayTimeout
        roomDm.status = DMSStatus.closing
        self.log.write('%s will close in %ds' % (url, roomDm.delayTimeout))
        #在disconnect期间又来说这个房间的dm是被需要的怎么处理呢？
        #这里又要分情况讨论，可能下一次超时事件依然是心跳，可能下一次超时就是直接关闭了
        #这一部分处理应该放在room_dm_connect中

    #超时事件：真正关闭dm server连接
    def room_dm_close(self, roomDm, current_time):
        if roomDm is None:
            return

        if roomDm.status != DMSStatus.closing:
            return

        self.log.write(roomDm.url + ' : room close...')

        #关闭可读连接池中中的
        for index, so in enumerate(self.inSockets):
            if roomDm.sock == so:
                del self.inSockets[index]
                self.log.write('del from in Sockets pool')
                break
        #关闭可写池的（没有，心跳包我以为没必要放到select中监听）
        #关闭dm server 池的
        if roomDm.Mark in self.Danmus:
            del self.Danmus[roomDm.Mark]
            self.log.write('del from Danmu Sockets pool')
        else:
            self.log.write('cannot del from in Sockets pool', 1)
        #删除存储在Server的MessageListBuffer里的key,value
        if self.messageListBuffer.deleteItem(roomDm.url):
            self.log.write('del from Danmu Sockets pool')
        else:
            self.log.write('cannot del from in Danmu pool', 1)

        #从定时器中删掉
        #返回值在正常情况下没用，且正常情况下要求输出：delete xxx fail, 返回False
        #还有一种情况看room_dm_connect函数第二分支的第一分支
        self.mainTimer.delTimer(roomDm, current_time)

        roomDm.sock.close()
        self.log.write(roomDm.url + ' : room close successfully...')

    #要在这里将下一次的心跳事件添加到定时器
    #同时还要看是否即将关闭，因为一个连接就一个超时事件的
    def keep_alive_event(self, current_time, roomDm):
        #发送心跳
        self.log.write(roomDm.url + ' : room keep alive...')
        roomDm.operation.keep_alive_package()
        nextKeepAlive = current_time + roomDm.keepAliveIntern
        timeout_intern = -1
        if roomDm.status == DMSStatus.closed:
            self.log.write('room is closed ???', 2)
            exit(-1)
        #如果连接即将断开，比较断开时间与下一次心跳时间
        elif roomDm.status == DMSStatus.closing:
            if roomDm.closingTimeout == -1:
                self.log.write('next closing timeout is -1 ???')
                exit(-1)
            if nextKeepAlive >= roomDm.closingTimeout:
                roomDm.timeoutEventType = DMTEventType.closing
                roomDm.timeoutEvent = self.room_dm_close
                timeout_intern = roomDm.closingTimeout - current_time

        if timeout_intern == -1:
            self.log.write(roomDm.url + ' : next timeout event : keep alive in ' + str(roomDm.keepAliveIntern) + 's')
            timeout_intern = roomDm.keepAliveIntern
        else:
            self.log.write(roomDm.url + ' : next timeout event : room close in ' + str(timeout_intern) + 's')

        self.mainTimer.addTimer(roomDm, timeout_intern, current_time)


    def timeout_process(self, current_time):
        #这里认为有超时事件的只有room socket
        while self.mainTimer.isTopTimeOut(current_time):
            (t, roomDm) = self.mainTimer.getPopTopTimer()
            if roomDm.timeoutEventType == DMTEventType.keepAlive:
                roomDm.timeoutEvent(current_time ,roomDm)
            elif roomDm.timeoutEventType == DMTEventType.closing:
                roomDm.timeoutEvent(roomDm, current_time)
            else:
                self.log.write('room timeoout event nothing ? ', 1)


#ws server发过来请求某个room的dm或者不再要某个room了
#数据格式是: type + 最多时人数(douyu room 人数，不是我这个网页上的人数,单位是万, 整型) +url
#在请求room时人数为0， 在取消room时人数用于决定该房间没人需要时多久后关闭
#type分为0和1,0为取消，1为需要
#传输方式为json
s = Server('127.0.0.1', 8666)
s.run()