"""Explicitly configured Chat Completions client; secrets stay on this host."""
import json
import os
import tempfile
import threading
import urllib.request
import urllib.error
from urllib.parse import urlsplit
from market import DataError


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ModelService:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def read(self):
        if not self.path.exists(): return {}
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict): raise ValueError()
            return data
        except (OSError, ValueError): raise DataError('模型配置无法读取，请重新保存。')

    def status(self):
        d = self.read()
        return {'base_url':d.get('base_url',''),'model':d.get('model',''), 'has_key':bool(d.get('key')), 'configured':bool(d.get('base_url') and d.get('model'))}

    def save(self, body):
        if not isinstance(body,dict): raise DataError('配置格式无效。')
        url, model, key = (body.get(k,'') for k in ('base_url','model','key'))
        if not all(isinstance(x,str) for x in (url,model,key)): raise DataError('配置字段必须是文本。')
        url,model,key=url.strip().rstrip('/'),model.strip(),key.strip()
        try: parsed=urlsplit(url); port=parsed.port
        except ValueError: raise DataError('模型地址无效。')
        local=parsed.hostname in ('127.0.0.1','localhost','::1')
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.scheme not in ('http','https') or (parsed.scheme=='http' and not local) or any(c.isspace() for c in url):
            raise DataError('请填写 HTTPS 模型地址；本机服务可使用 HTTP。地址不要包含密钥、参数或账号。')
        if not model or len(model)>200 or len(url)>1000 or len(key)>4096 or any(ord(c)<32 for c in model+key): raise DataError('模型名称或密钥格式无效。')
        with self.lock:
            old=self.read()
            if not key and not body.get('clear_key'):
                if old.get('key') and old.get('base_url')!=url: raise DataError('更换服务地址时，请重新输入密钥或勾选清除密钥，避免误发到其他服务。')
                key=old.get('key','')
            if not local and not key: raise DataError('远程模型服务需要填写 API Key。')
            data={'base_url':url,'model':model,'key':key}
            self.path.parent.mkdir(parents=True,exist_ok=True)
            fd,tmp=tempfile.mkstemp(dir=self.path.parent,prefix='.model-')
            try:
                with os.fdopen(fd,'w') as f: json.dump(data,f,ensure_ascii=False)
                os.replace(tmp,self.path)
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
        return self.status()

    def complete(self, messages, config=None, max_tokens=2400):
        d=dict(config if config is not None else self.read())
        if not d.get('base_url') or not d.get('model'): raise DataError('尚未配置模型，请先到设置页填写模型服务。')
        body=json.dumps({'model':d['model'],'messages':messages,'max_tokens':max_tokens,'stream':False},ensure_ascii=False).encode()
        headers={'Content-Type':'application/json'}
        if d.get('key'):headers['Authorization']='Bearer '+d['key']
        request=urllib.request.Request(d['base_url']+'/chat/completions',data=body,headers=headers)
        try:
            with urllib.request.build_opener(NoRedirect).open(request,timeout=90) as response:
                raw=response.read(1000001)
            if len(raw)>1000000:raise DataError('模型响应过大，未保存解读。')
            result=json.loads(raw)
            choice=result['choices'][0]
            if choice.get('finish_reason')=='length':raise DataError('模型输出被截断，请换用支持更长输出的模型后重试。')
            text=choice['message']['content']
            if not isinstance(text,str) or not text.strip():raise ValueError()
            return text
        except urllib.error.HTTPError as e:
            raise DataError(f'模型服务返回 HTTP {e.code}，请核对地址、权限、额度和模型名称。') from None
        except DataError:raise
        except Exception:raise DataError('模型连接失败或响应格式不兼容，请检查服务后重试。') from None

    def test(self):
        self.complete([{'role':'user','content':'Reply only with OK.'}],max_tokens=32)
        return {'message':'模型已返回有效响应。分析报告的格式兼容性将在生成时另行校验。'}
