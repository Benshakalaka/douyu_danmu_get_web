/**
 * Created by Ben on 2016/4/14.
 */
$(document).ready(function(){
    //既然我这里使用了bootstrap的模态框，就用他提供的函数
	//$(".danmuOpenBtn").click(function(){
	//	thisNode = $(this);
	//	title = thisNode.parent().children('#live-title').text();
	//	roomUrl = thisNode.attr('id');
    //
	//	//要设置超时，是因为modal是在click事件后出来的，要在modal出来后设置才有用
	//	setTimeout(function(){
	//		$("#danmu-title").text(title);
	//	}, 100);
	//})

    //这里我使用websocket连接到另一个服务器获取弹幕，该放服务器专门用于获取弹幕
    //每个页面只允许获取一个房间的弹幕
    var ws = new WebSocket('ws://127.0.0.1:5005');
    websocketInit(ws);
    //ws是否连接
    var connectStatus = false;
    var sysName = '系统提示';
    var danmuModal = $("#danmuModal");

    //网页当前状态
    var WSStatus = {
        //正在请求弹幕
        connecting: 0,
        //即将发送关闭请求
        closing   : 1,
        //当前无请求
        closed    : 2
    };

    //网页正在监听的room信息
    var currRoomInfo = {
        title : '',
        tag   : '',
        host  : '',
        people: '',
        url   : '',
        //ws 是否有请求弹幕
        status: WSStatus.closed,
        //即将关闭的定时器
        closingTimer : null
    };

    //type为1表示连接， peopleMax在type为1的时候为-1，因为此时该数据无用
    function Msg2server(type, peopleMax){
        this.data = {};
        this.data['type'] = type;
        this.data['url'] = currRoomInfo['url'];
        if(peopleMax != -1){
            this.data['peopleMax'] = peopleMax;
        }
    }

    Msg2server.prototype = {
        constructor : Msg2server,
        getJsonData : function(){
            return JSON.stringify(this.data);
        }
    };

    // 我感觉这个动作太轻了，容易诱发快速点击，所以可以设置延迟关闭
    // 也可以让ws server延迟发送room disconnect信息
    function openUrl(triggerBtn){
        $(".single-message").remove();

        currRoomInfo['title'] = triggerBtn.parent().children('#live-title').text();
        currRoomInfo['tag'] = triggerBtn.parent().children('#live-tag').text();
        currRoomInfo['host'] = triggerBtn.parent().children('#live-host').text();
        //默认people字段的值是 130000 这样的显示方式
        currRoomInfo['people'] = triggerBtn.parent().children('#live-people').text();
        currRoomInfo['people'] = parseInt(currRoomInfo['people']) / 10000;
        currRoomInfo['url'] = triggerBtn.prev().attr('href');
        currRoomInfo['status'] = WSStatus.connecting;

        $("#danmu-title").text(currRoomInfo['title']);

        addMsgToBody(sysName, '正在连接...', 1);
        var data_1 = new Msg2server(1, -1);
        ws.send(data_1.getJsonData());
    }

    function closeUrl(){
        var data = new Msg2server(0, currRoomInfo['people']);
        ws.send(data.getJsonData());
        currRoomInfo['status'] = WSStatus.closed;
        currRoomInfo.closingTimer = null;
    }

    danmuModal.on('show.bs.modal', function(event){
        var triggerBtn = $(event.relatedTarget);
        if(currRoomInfo.status == WSStatus.closed) {
            openUrl(triggerBtn);
        }else if(currRoomInfo.status == WSStatus.closing){
            href = triggerBtn.prev().attr('href');
            clearTimeout(currRoomInfo.closingTimer);
            if(href == currRoomInfo.url){
                currRoomInfo.status = WSStatus.connecting;
                currRoomInfo.closingTimer = null;
            }else{
                closeUrl();
                openUrl(triggerBtn);
            }
        }else{
            //出错
        }
    });

    function websocketInit(ws){
        ws.onopen = openON;
        ws.onerror = errorON;
        ws.onmessage = messageON;
        ws.onclose = closeON;
    }

    function openON(){
        //连接成功后调用函数
        connectStatus = true;
        //addMsgToBody(sysName, '连接成功！开始接收...', 1)
    }

    function errorON(e){
        //提示信息
        //addMsgToBody(sysName, '连接错误！请刷新重试...', 2);
        connectStatus = false;
    }

    function closeON(){
        //如果连接失败，会先触发err事件，之后是这个close事件
        if(connectStatus == true){
            addMsgToBody(sysName, '连接终止！', 2);
            connectStatus = false;
        }
    }

    function messageON(e){
        if(currRoomInfo.status == WSStatus.connecting) {
            content = JSON.parse(e.data);
            for (var index = 0; index < content.length; index++) {
                var single_msg = content[index];
                var single_msg_list = single_msg.split('/');
                var type = single_msg_list[0].slice(6);
                addMsgToBody(single_msg_list[1].slice(10), single_msg_list[2].slice(5), 0);
            }
        }
    }

    //type: 0-正常   1-系统提示（正常）  2-系统提示（错误）
    function addMsgToBody(name, message, type){
        var wrapper = $("<div />", {
            class : 'single-message'
        });

        switch(type){
            case 0:
                uN_class = 'normal_uN';
                msg_class = 'normal_msg';
                break;
            case 1:
                uN_class = 'normal_sys';
                msg_class = 'normal_sys';
                break;
            case 2:
                uN_class = 'normal_sys';
                msg_class = 'error_sys';
                break;
        }

        $("<label />", {
            text : name,
            class : uN_class
        }).appendTo(wrapper);

        $("<p />", {
            text : message,
            class : msg_class
        }).appendTo(wrapper);

        var content_to_end = $("#content-body");
        wrapper.appendTo(content_to_end);
        content_to_end.scrollTop(content_to_end[0].scrollHeight);
    }


    danmuModal.on('hide.bs.modal', function(event){
        $(".single-message").remove();
        currRoomInfo['status'] = WSStatus.closing;
        //我把即将关闭的延迟时间在这里设置为10秒
        currRoomInfo['closingTimer'] = setTimeout(function(){
            closeUrl();
        }, 10000);
    });


    $("#resetBtn").click(function(){
        $(".single-message").remove();
    })

});
