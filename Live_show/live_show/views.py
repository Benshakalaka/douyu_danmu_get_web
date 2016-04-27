from django.shortcuts import render_to_response
import re
import requests
import json
import time
from urllib import parse
from hashlib import md5
import socket,select
import uuid
import struct
# Create your views here.
# def get_room_detail(room_address):
#     room_page = requests.get(room_address)
#     room_info = re.search(r'id="live_userinfo">(.*?)<div class="show"', room_page.text, re.S)
#     print(room_info.group(1))
#     auth_icon = re.search(r'<img src="(.*?)"', room_info.group(1))


#斗鱼房间列表
def douyu_get(total_count):
    #斗鱼里使用了jQuery Lazy Load， http://code.ciaoca.com/jquery/lazyload/
    #即在滚动到那里的时候图片才加载，减轻了初始加载压力
    douyu_url = "http://www.douyu.com/directory/all"
    douyu_url_room = 'http://www.douyu.com'
    douyu_main_page = requests.get(douyu_url)
    live_all = re.search(r'<ul id="live-list-contentbox"(.*?)</ul>', douyu_main_page.text, re.S)
    live_list = re.findall(r'<li (.*?)</li>', live_all.group(1), re.S)
    all_live = []
    count = 0
    for live_single in live_list:
        live_one = {}
        href = re.search(r'href="(.*?)"', live_single).group(1)
        live_one['href'] = douyu_url_room + href
        live_one['title'] = re.search(r'title="(.*?)"', live_single).group(1)
        live_one['img_url'] = re.search(r'data-original="(.*?)"', live_single).group(1)
        live_one['tag'] = re.search(r'ellipsis">(.*?)</span>', live_single).group(1)
        live_one['auth'] = re.search(r'ellipsis fl">(.*?)</span>', live_single).group(1)
        live_one['audience'] = re.search(r'dy-num fr">(.*?)</span>', live_single).group(1)

        all_live.append(live_one)
        count += 1
        if count == total_count:
            break

    return all_live


#龙珠房间列表获取
def longzhu_get(total_count):
    longzhu_url = 'http://www.longzhu.com/channels/all'
    longzhu_main_page = requests.get(longzhu_url)
    live_all = re.search(r'<div class="list-con" id="list-con" style="min-height: 0;">(.*?)</div>', longzhu_main_page.text, re.S)
    live_list = re.findall(r'<a (.*?)</a>', live_all.group(1), re.S)
    all_live = []
    count = 0
    for live_single in live_list:
        live_one = {}
        live_one['href'] = re.search(r'href="(.*?)"', live_single).group(1)
        live_one['title'] = re.search(r'title="(.*?)"', live_single).group(1)
        live_one['img_url'] = re.search(r'src="(.*?)"', live_single).group(1)
        live_one['auth'] = re.search(r'livecard-modal-username">(.*?)</strong>', live_single).group(1)
        aud_and_tag = re.findall(r'class="livecard-meta-item-text">(.*?)</span>', live_single)
        live_one['audience'] = aud_and_tag[0]
        live_one['tag'] = aud_and_tag[1]

        all_live.append(live_one)
        count += 1
        if count == total_count:
            break

    # for live_single in all_live:
    #     for live_data in live_single:
    #         print(live_data + ' : ' + live_single[live_data])
    #     print('')

    return all_live




#全民房间列表获取
def quanmin_get(total_count):
    #全民与上面两个不一样，上面两个传回来的是静态页面，里面主播列表什么的都是完整列表
    #但是全民，返回的静态页面是个框架，主要靠json数据来渲染整个页面，所以可以看出全民在刷新后页面主题部分是loading状态，而其他两个网站则全显示出来了
    #所以这里获取的是json数据
    quanmin_url = 'http://www.quanmin.tv/json/play/list.json?t=24314740'
    quanmin_url_room = 'http://www.quanmin.tv/v/'
    quanmin_json = requests.get(quanmin_url)
    quanmin_data = json.loads(quanmin_json.text, encoding='utf-8')

    all_live = []
    count = 0
    for live_single in quanmin_data['data']:
        live_one = {}
        live_one['href'] = quanmin_url_room + live_single['uid']
        live_one['title'] = live_single['title']
        live_one['img_url'] = live_single['thumb']
        live_one['auth'] = live_single['nick']
        live_one['audience'] = live_single['view']
        live_one['tag'] = live_single['category_name']

        all_live.append(live_one)
        count += 1
        if count == total_count:
            break

    return all_live

#既然有很多图片需求，就可以像斗鱼那样先加载默认图片，之后替换
def live_show(request):
    d_info = {}
    d_list = douyu_get(8)
    d_info['platform_src'] = 'http://shark.douyucdn.cn/app/douyu/res/com/logo.png?20160303'
    d_info['platform_name'] = 'douyu'
    d_info['players'] = d_list

    l_info = {}
    l_list = longzhu_get(8)
    l_info['platform_src'] = 'http://r.plures.net/plu/images/small-longzhu-logo.png'
    l_info['platform_name'] = 'longzhu'
    l_info['players'] = l_list

    q_info = {}
    q_list = quanmin_get(8)
    q_info['platform_src'] = 'https://ss0.bdstatic.com/-0U0bnSm1A5BphGlnYG/tam-ogel/a51cd39b2c356de3f27959ffefb369fe_121_121.jpg'
    q_info['platform_name'] = 'quanmin'
    q_info['players'] = q_list

    live_list = {}
    live_list['douyu'] = d_info
    live_list['longzhu'] = l_info
    live_list['quanmin'] = q_info
    return render_to_response("live_show_2.html", {'live_list':live_list})
