"""Bounded public-source collector. No credentials, automatic retries or hidden redirects."""
import datetime as dt
import hashlib
import gzip
import io
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

HOSTS = frozenset(('www.sse.com.cn','static.sse.com.cn','query.sse.com.cn','static.cninfo.com.cn','www.cninfo.com.cn','www.szse.cn'))
UA = {'User-Agent':'Mozilla/5.0 (compatible; guanshi-public-evidence/1.0)', 'Accept':'*/*'}


def now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def sha(body): return hashlib.sha256(body).hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


class Collector:
    def __init__(self, folder, max_requests=10, transport=None):
        self.folder=Path(folder); self.path=self.folder/'ledger.json'
        self.data=json.loads(self.path.read_text()) if self.path.exists() else {
            'schema_version':1,'created_at':now(),'max_requests':max_requests,'requests':[]}
        if not 1<=max_requests<=50 or not 1<=self.data['max_requests']<=50:
            raise ValueError('maximum 50 requests per round; default 10')
        self.transport=transport or urllib.request.build_opener(NoRedirect()).open

    def save(self):
        self.folder.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(self.data,ensure_ascii=False,indent=2)+'\n')
        temp.replace(self.path)

    @staticmethod
    def check_url(url):
        parts=urllib.parse.urlsplit(url)
        if parts.scheme!='https' or parts.hostname not in HOSTS or parts.username or parts.password:
            raise ValueError('only listed public HTTPS sources allowed')
        if parts.port not in (None,443): raise ValueError('unexpected port')
        if any(k.lower() in ('key','api_key','apikey','token','password','cookie','authorization')
               for k,v in urllib.parse.parse_qsl(parts.query)):
            raise ValueError('credentials forbidden')

    def fetch(self,url,*,headers=None,data=None,method='GET',name='public',max_redirects=3,expect=None,max_bytes=64*1024*1024):
        expect=expect or ('pdf' if urllib.parse.urlsplit(url).path.lower().endswith('.pdf') else None)
        caller=dict(headers or {})
        if any(k.lower() in ('authorization','cookie','x-api-key') for k in caller):
            raise ValueError('credentials forbidden')
        if method not in ('GET','POST'): raise ValueError('only public read queries supported')
        if not 1<=max_bytes<=64*1024*1024: raise ValueError('invalid response size limit')
        sent={**UA,**caller}; body=data.encode() if isinstance(data,str) else data
        if body is not None and not isinstance(body,bytes): raise TypeError('request data must be bytes or text')
        for hop in range(max_redirects+1):
            self.check_url(url)
            if len(self.data['requests'])>=self.data['max_requests']:
                return {'ok':False,'stop':'budget_exhausted'}
            host=urllib.parse.urlsplit(url).hostname
            recent=[r for r in self.data['requests'] if urllib.parse.urlsplit(r['url']).hostname==host]
            if any(r.get('status') in (401,402,403,429) for r in recent):
                return {'ok':False,'stop':'access_or_rate_limit'}
            if len(recent)>=2 and all(not r.get('ok') and r.get('status') not in (301,302,303,307,308) for r in recent[-2:]):
                return {'ok':False,'stop':'repeated_source_failure'}
            rec={'id':len(self.data['requests'])+1,'name':name,'url':url,'method':method,
                 'request_headers':sent,'request_body_utf8':body.decode('utf-8') if body is not None else None,
                 'request_body_sha256':sha(body) if body is not None else None,
                 'started_at':now(),'redirect_hop':hop,'response_limit_bytes':max_bytes,'result':'in_flight','ok':False}
            self.data['requests'].append(rec);self.save() # count before dispatch, even if process dies
            request=urllib.request.Request(url,headers=sent,method=method,data=body)
            response=None
            try:
                try: response=self.transport(request,timeout=20)
                except urllib.error.HTTPError as exc: response=exc
                payload=response.read(max_bytes+1)
                rec['status']=response.status if hasattr(response,'status') else response.code
                rec['response_headers']={k:v for k,v in response.headers.items() if k.lower() in
                    ('content-type','content-encoding','location','last-modified','content-length','etag')}
                raw=f"raw/{rec['id']:03d}.bin";path=self.folder/raw;path.parent.mkdir(exist_ok=True)
                with path.open('xb') as stream: stream.write(payload)
                rec.update(raw=raw,sha256=sha(payload),bytes=len(payload),fetched_at=now(),
                    result='response',raw_complete=len(payload)<=max_bytes,ok=200<=rec['status']<300)
                if len(payload)>max_bytes:
                    rec.update(ok=False,result='response_too_large',raw_complete=False)
                if expect=='pdf' and rec['ok']:
                    decoded=payload
                    if payload.startswith(b'\x1f\x8b'):
                        decoded=gzip.GzipFile(fileobj=io.BytesIO(payload)).read(max_bytes+1)
                    if len(decoded)>max_bytes:
                        rec.update(ok=False,result='decoded_response_too_large',decoded_complete=False)
                    rec['expected_format']='pdf'
                    if not decoded.startswith(b'%PDF-'):
                        rec.update(ok=False,result='unexpected_content')
                self.save()
                if rec['status'] in (301,302,303,307,308):
                    location=response.headers.get('Location')
                    if not location or hop==max_redirects: return {**rec,'ok':False,'stop':'redirect_limit'}
                    url=urllib.parse.urljoin(url,location)
                    if rec['status']==303 or (rec['status'] in (301,302) and method=='POST'):
                        method,body='GET',None
                    continue
                return rec
            except (OSError,ValueError,urllib.error.URLError) as exc:
                rec.update(result='transport_error',error=f'{type(exc).__name__}: {exc}',finished_at=now(),ok=False)
                self.save();return rec
            finally:
                if response is not None: response.close()
        raise AssertionError('redirect loop escaped')

    def replay(self):
        rows=[]
        for rec in self.data['requests']:
            row={'id':rec['id'],'url':rec['url'],'http_status':rec.get('status'),'transport_ok':rec.get('ok',False),
                 'raw_complete':rec.get('raw_complete',rec.get('result')!='response_too_large')}
            if not rec.get('sha256') or not rec.get('raw'): row['integrity']='unverified'
            else:
                path=self.folder/rec['raw']
                row['integrity']='match' if path.is_file() and sha(path.read_bytes())==rec['sha256'] else 'failed'
            rows.append(row)
        status='failed' if any(x['integrity']=='failed' for x in rows) else 'incomplete' if any(not x['raw_complete'] for x in rows) else (
            'pass' if rows and all(x['integrity']=='match' for x in rows) else 'unverified')
        return {'status':status,'attempts':len(rows),'matched':sum(x['integrity']=='match' for x in rows),
                'transport_successes':sum(x['transport_ok'] for x in rows),'rows':rows}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',required=True);parser.add_argument('--url');parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if args.execute:
        if not args.url: parser.error('--execute requires --url')
        result=Collector(args.folder).fetch(args.url);print(json.dumps(result,ensure_ascii=False,indent=2))
        raise SystemExit(0 if result.get('ok') else 1)
    result=Collector(args.folder).replay() if Path(args.folder,'ledger.json').exists() else {'status':'dry_run','url':args.url}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['status'] in ('pass','dry_run') else 1)
