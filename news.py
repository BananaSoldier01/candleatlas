"""Unauthenticated Sina public news feed, fetched only on demand."""
import datetime as dt
from html.parser import HTMLParser
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from market import DataError, TZ

class PlainText(HTMLParser):
    def __init__(self): super().__init__(); self.parts=[]; self.skip=0
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style'): self.skip+=1
        if tag in ('br','p','div'): self.parts.append(' ')
    def handle_endtag(self, tag):
        if tag in ('script','style'): self.skip=max(0,self.skip-1)
    def handle_data(self, data):
        if not self.skip:self.parts.append(data)

def plain(value):
    parser=PlainText();parser.feed(str(value or ''))
    return ' '.join(''.join(parser.parts).split())

def associations(row):
    try: ext=json.loads(row.get('ext') or '{}')
    except (ValueError,TypeError): ext={}
    stocks=[];topics=set()
    for tag in row.get('tag') or []:
        if isinstance(tag,dict) and tag.get('name'):topics.add(plain(tag['name']))
    for item in ext.get('stocks',[]) if isinstance(ext,dict) else []:
        if not isinstance(item,dict):continue
        symbol=item.get('symbol','');name=plain(item.get('key'))
        if not name:continue
        if item.get('market')=='cn' and re.fullmatch(r'(sh6\d{5}|sz[03]\d{5}|bj[489]\d{5})',symbol):
            code=symbol[2:]+'.'+symbol[:2].upper()
            if not any(x['thscode']==code for x in stocks):stocks.append({'thscode':code,'name':name})
        elif item.get('market')=='cn' and symbol.startswith('si'):topics.add(name)
    return stocks,sorted(topics)

def normalize(rows):
    result=[];seen=set()
    for r in rows:
        if not isinstance(r,dict):continue
        parser=PlainText();parser.feed(str(r.get('rich_text') or ''))
        content=' '.join(''.join(parser.parts).split())
        stamp=r.get('create_time','')
        try:dt.datetime.strptime(stamp,'%Y-%m-%d %H:%M:%S')
        except (ValueError,TypeError):continue
        identity=str(r.get('id') or '')
        if not content or not identity or identity in seen:continue
        seen.add(identity)
        url=r.get('docurl') or ''
        parts=urllib.parse.urlparse(url)
        if parts.scheme not in ('http','https') or parts.hostname not in ('finance.sina.cn','finance.sina.com.cn') or parts.username:
            url=''
        stocks,topics=associations(r)
        result.append({'stocks':stocks,'topics':topics,'id':identity,'time':stamp,'content':content,'url':url,'source':'新浪财经'})
    return sorted(result,key=lambda r:(r['time'],r['id']),reverse=True)

class News:
    def __init__(self,directory):
        self.directory=directory;directory.mkdir(parents=True,exist_ok=True)
        self.path=directory/'sina-latest-v2.json';self.lock=threading.Lock()
    def fetch(self):
        params=dict(page=1,page_size=100,zhibo_id=152,tag_id=0,dire='f',dpc=1,pagesize=100,type=1)
        req=urllib.request.Request('https://zhibo.sina.com.cn/api/zhibo/feed?'+urllib.parse.urlencode(params),headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req,timeout=15) as response: data=json.load(response)
        items=normalize(data['result']['data']['feed']['list'])
        if not items:raise DataError('新浪暂无有效快讯。')
        return {'items':items,'fetched_at':time.time(),'updated_at':dt.datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')}
    def get(self):
        return self.cached(self.path,self.fetch,60)

    def stock(self,code,end):
        if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',code):raise DataError('股票代码无效。')
        try: day=dt.date.fromisoformat(end)
        except ValueError:raise DataError('资讯截止日期无效。') from None
        if day>dt.datetime.now(TZ).date():raise DataError('不能选择未来日期。')
        data=self.cached(self.directory/('eastmoney-'+code+'.json'),lambda:self.fetch_stock(code),300)
        return {**data,'code':code,'end':end,'items':[r for r in data['items'] if r['time'][:10]<=end],
                'note':'按股票代码检索最近 10 条结果，并过滤观察日之后的消息；不代表完整历史，搜索结果可能只是提及该股票。'}

    def fetch_stock(self,code):
        params={'uid':'','keyword':code[:6],'type':['cmsArticleWebOld'],'client':'web','clientType':'web','clientVersion':'curr',
                'param':{'cmsArticleWebOld':{'searchScope':'default','sort':'time','pageIndex':1,'pageSize':10,'preTag':'','postTag':''}}}
        url='https://search-api-web.eastmoney.com/search/jsonp?'+urllib.parse.urlencode({'cb':'newsFeed','param':json.dumps(params)})
        request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Referer':'https://so.eastmoney.com/'})
        with urllib.request.urlopen(request,timeout=15) as response: text=response.read().decode()
        text=text.strip()
        if text.startswith('newsFeed('):text=text[len('newsFeed('):text.rfind(')')]
        data=json.loads(text);rows=data['result']['cmsArticleWebOld']
        if not isinstance(rows,list):raise DataError('个股资讯返回格式无效。')
        items=[];seen=set()
        for r in rows:
            identity=str(r.get('code') or '');stamp=r.get('date','')
            try:dt.datetime.strptime(stamp,'%Y-%m-%d %H:%M:%S')
            except (ValueError,TypeError):continue
            title=plain(r.get('title'))
            if not identity.isdigit() or identity in seen or not title:continue
            seen.add(identity)
            items.append({'id':identity,'time':stamp,'title':title,'content':plain(r.get('content')),
                          'source':plain(r.get('mediaName')) or '东方财富','url':'https://finance.eastmoney.com/a/'+identity+'.html'})
        if rows and not items:raise DataError('个股资讯没有有效记录。')
        return {'items':sorted(items,key=lambda r:r['time'],reverse=True),'fetched_at':time.time(),
                'updated_at':dt.datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')}

    def cached(self,path,fetch,ttl):
        with self.lock:
            cached=None
            try:
                cached=json.loads(path.read_text())
                if not isinstance(cached.get('items'),list) or not isinstance(cached.get('fetched_at'),(int,float)):cached=None
            except (OSError,ValueError):pass
            if cached and 0<=time.time()-cached['fetched_at']<ttl:return {**cached,'stale':False}
            try:
                data=fetch()
                tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False));tmp.chmod(0o600);tmp.replace(path)
                return {**data,'stale':False}
            except Exception:
                if cached:return {**cached,'stale':True,'warning':'更新失败，以下为上次缓存，不是最新快讯。'}
                raise DataError('资讯暂时无法获取，请稍后刷新。') from None
