"""Loopback-only dashboard; never exposes project files or API credentials."""
import argparse
import errno
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from market import ROOT, Market, DataError
from intraday import Intraday
from rankings import Rankings
import settings
from news import News
from theme_clues import ThemeClues
from announcement_clues import AnnouncementClues
from tracking import Tracking, followup
from workbench import summary as workbench_summary
from model_service import ModelService
from analysis import Analysis
from report_batch import BatchService
from batch import BatchError
from chan_structure import for_market as chan_for_market
from disclosures import DisclosureStore

STATIC = {'/workbench.js': ('workbench.js', 'text/javascript'), '/chan.js': ('chan.js', 'text/javascript'), '/analysis.js': ('analysis.js', 'text/javascript'), '/navigation.js': ('navigation.js', 'text/javascript'), '/overview.js': ('overview.js', 'text/javascript'), '/tracking.js': ('tracking.js', 'text/javascript'), '/theme-clues.js': ('theme-clues.js', 'text/javascript'), '/clues.js': ('clues.js', 'text/javascript'), '/news.js': ('news.js', 'text/javascript'), '/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
          '/workspace.js': ('workspace.js', 'text/javascript'),
          '/intraday.js': ('intraday.js', 'text/javascript'),
          '/rankings.js': ('rankings.js', 'text/javascript'),
          '/settings.js': ('settings.js', 'text/javascript'),
          '/style.css': ('style.css', 'text/css')}


STATIC['/demo.js'] = ('demo.js', 'text/javascript')
STATIC['/batch.js'] = ('batch.js', 'text/javascript')
STATIC['/price-technical.js'] = ('price-technical.js', 'text/javascript')
STATIC['/guide-content.js'] = ('guide-content.js', 'text/javascript')
STATIC['/guide.js'] = ('guide.js', 'text/javascript')
STATIC['/guide.css'] = ('guide.css', 'text/css')
STATIC['/label-rules.js'] = ('label-rules.js', 'text/javascript')
STATIC['/privacy.js'] = ('privacy.js', 'text/javascript')
STATIC['/attention.js'] = ('attention.js', 'text/javascript')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, content, kind='application/json'):
        if not isinstance(content, bytes):
            content = json.dumps(content, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind + '; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        port = self.server.server_port
        if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}') or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return self.send(403, {'error': '仅允许本机同源访问'})
        origin = self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
            return self.send(403, {'error': '禁止跨站访问'})
        if getattr(self.server,'demo',None) is not None:
            return self.send(403,{'error':'演示模式只读：不保存配置、记录，不发起分析或模型请求。','reason':'demo_read_only'})
        parsed = urlparse(self.path)
        if parsed.path in ('/api/batch', '/api/batch/cancel', '/api/batch/retry', '/api/batch/review'):
            if origin not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
                return self.send(403, {'error': '批次操作需要从本机同源页面发起'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json' or not 0 < length <= 64000:
                    return self.send(400, {'error': '请求格式无效'})
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    return self.send(400, {'error': '请求格式无效'})
                if parsed.path == '/api/batch':
                    result = self.server.batch.submit(body)
                elif parsed.path == '/api/batch/cancel':
                    result = self.server.batch.cancel(body.get('id'))
                elif parsed.path == '/api/batch/retry':
                    result = self.server.batch.retry(body.get('id'))
                else:
                    result = self.server.batch.review(body.get('id'), body.get('index'))
                return self.send(202 if parsed.path in ('/api/batch', '/api/batch/retry') else 200, result)
            except (DataError, BatchError) as e:
                return self.send(400, {'error': str(e)})
            except (ValueError, TypeError):
                return self.send(400, {'error': '请求格式无效'})
            except Exception:
                return self.send(500, {'error': '批次操作未能完成，请刷新状态核对已有报告。'})
        if parsed.path in ('/api/model-settings','/api/model-settings/test','/api/analysis'):
            if origin not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
                return self.send(403, {'error':'操作需要从本机同源页面发起'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if self.headers.get('Content-Type','').split(';')[0]!='application/json' or not 0<length<=12000:
                    return self.send(400,{'error':'请求格式无效'})
                body=json.loads(self.rfile.read(length))
                if parsed.path=='/api/model-settings':result=self.server.model.save(body)
                elif parsed.path=='/api/model-settings/test':result=self.server.model.test()
                else:result=self.server.analysis.start(body)
                return self.send(202 if parsed.path=='/api/analysis' else 200,result)
            except (DataError,ValueError) as e:return self.send(400,{'error':str(e) if isinstance(e,DataError) else '请求格式无效'})
            except Exception:return self.send(500,{'error':'分析或配置操作失败，请稍后重试。'})
        if parsed.path == '/api/observations':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json' or not 0 < length <= 4000000:
                    return self.send(400, {'error': '需要有效 JSON 记录'})
                return self.send(200, self.server.tracking.save(json.loads(self.rfile.read(length))))
            except (ValueError, DataError) as e:
                return self.send(400, {'error': str(e)})
            except Exception:
                return self.send(500, {'error': '记录未能保存，请稍后重试；原记录保留。'})
        if parsed.path in ('/api/settings', '/api/settings/test'):
            if origin not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
                return self.send(403, {'error': '配置操作需要同源页面'})
            try:
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    return self.send(415, {'error': '需要 JSON 请求'})
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 8192:
                    return self.send(400, {'error': '请求大小无效'})
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    return self.send(400, {'error': '配置格式无效'})
                if parsed.path == '/api/settings/test':
                    self.server.market.get('calendar/trading-days', ttl=0)
                    return self.send(200, {'message': '连接成功，当前 Key 可访问交易日历。其他接口权限以账号授权为准。'})
                result = settings.save_key(body.get('key'))
                return self.send(200, {**result, 'message': '已保存并生效。可测试连接后返回市场页面刷新数据。'})
            except (DataError, ValueError) as e:
                return self.send(400, {'error': str(e) if isinstance(e, DataError) else '配置格式无效'})
            except Exception:
                return self.send(500, {'error': '配置操作失败，请检查本地文件权限或稍后重试'})
        if parsed.path != '/api/sync-day':
            return self.send(404, {'error': '未找到'})
        try:
            day = parse_qs(parsed.query).get('date', [''])[0]
            self.send(200, self.server.market.sync_day(day))
        except (DataError, ValueError) as e:
            self.send(400, {'error': str(e)})
        except Exception:
            self.send(500, {'error': '同步失败，已有归档保留'})

    def do_GET(self):
        port = self.server.server_port
        if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            return self.send(403, {'error': '仅允许本机访问'})
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return self.send(403, {'error': '禁止跨站访问'})
        parsed = urlparse(self.path)
        if parsed.path=='/favicon.ico':return self.send(204,b'','image/x-icon')
        if parsed.path in STATIC:
            name, kind = STATIC[parsed.path]
            return self.send(200, (ROOT / 'web' / name).read_bytes(), kind)
        query = parse_qs(parsed.query)
        try:
            if getattr(self.server,'demo',None) is not None and parsed.path.startswith('/api/'):
                return self.send(200,self.server.demo.get(parsed.path,query))
            if parsed.path=='/api/runtime':return self.send(200,{'mode':'live','read_only':False,'synthetic':False})
            if parsed.path == '/api/disclosures':
                return self.send(200,self.server.disclosures.query(query.get('code',[''])[0],query.get('date',[''])[0],query.get('report',[''])[0]))
            if parsed.path == '/api/batch':
                identifier = query.get('id', [''])[0]
                return self.send(200, self.server.batch.snapshot(identifier) if identifier else self.server.batch.history(query.get('date', [''])[0]))
            if parsed.path == '/api/workbench':
                return self.send(200,workbench_summary(self.server.tracking,self.server.analysis,query.get('date',[''])[0]))
            if parsed.path == '/api/model-settings':
                return self.send(200,self.server.model.status())
            if parsed.path == '/api/analysis-history':
                return self.send(200,self.server.analysis.history(query.get('code',[''])[0]))
            if parsed.path == '/api/analysis':
                return self.send(200,self.server.analysis.get(query.get('id',[''])[0]))
            if parsed.path == '/api/observations':
                return self.send(200, self.server.tracking.list())
            if parsed.path == '/api/followup':
                return self.send(200, followup(self.server.market,query.get('code',[''])[0],query.get('observed',[''])[0],query.get('date',[''])[0]))
            if parsed.path == '/api/overview-dates':
                dates=self.server.market.calendar()
                return self.send(200, {'dates':[d for d in dates if self.server.rankings.read(d+'-market.json')]})
            if parsed.path == '/api/overview':
                return self.send(200, self.server.rankings.overview(query.get('date',[''])[0]))
            if parsed.path == '/api/clue-history':
                return self.send(200, self.server.theme_clues.history(query.get('date',[''])[0],query.get('kind',['topics'])[0],query.get('key',[''])[0]))
            if parsed.path == '/api/clue-catalog':
                return self.send(200,self.server.theme_clues.catalog(query.get('date',[''])[0],query.get('kind',['topics'])[0]))
            if parsed.path == '/api/clue-detail':
                return self.send(200,self.server.theme_clues.detail(query.get('date',[''])[0],query.get('kind',['topics'])[0],query.get('key',[''])[0]))
            if parsed.path == '/api/clue-financial':
                return self.send(200,self.server.theme_clues.financial(query.get('code',[''])[0],query.get('report',[''])[0]))
            if parsed.path == '/api/movers':
                return self.send(200,self.server.rankings.movers(query.get('date',[''])[0],query.get('direction',['up'])[0],float(query.get('threshold',['5'])[0]),int(query.get('offset',['0'])[0])))
            if parsed.path == '/api/stock-news':
                return self.send(200, self.server.news.stock(query.get('code',[''])[0],query.get('date',[''])[0]))
            if parsed.path == '/api/news':
                return self.send(200, self.server.news.get())
            if parsed.path == '/api/settings':
                return self.send(200, settings.status())
            if parsed.path == '/api/health':
                return self.send(200, {'app': 'stock-board', 'status': 'ok'})
            if parsed.path == '/api/calendar':
                return self.send(200, {'dates': self.server.market.calendar()})
            if parsed.path == '/api/search':
                return self.send(200, self.server.market.search(query.get('q', [''])[0]))
            end = query.get('date', [''])[0]
            days = int(query.get('days', ['20'])[0])
            if days not in (5, 10, 20):
                raise DataError('仅支持 5、10、20 个交易日。')
            if parsed.path == '/api/rankings':
                result = self.server.rankings.get(end, query.get('kind',['hot'])[0], query.get('period',['day'])[0], int(query.get('offset',['0'])[0]), int(query.get('limit',['10'])[0]))
            elif parsed.path == '/api/intraday':
                result = self.server.intraday.series(query.get('code', [''])[0], end, query.get('mode', ['intraday'])[0], int(query.get('interval', ['1'])[0]), int(query.get('count', ['120'])[0]), self.server.market.calendar())
            elif parsed.path == '/api/counts':
                result = self.server.market.counts(end, days)
            elif parsed.path == '/api/hot':
                result = self.server.market.hot(end)
            elif parsed.path == '/api/trend':
                result = self.server.market.trend(query.get('code', [''])[0], end, days)
            elif parsed.path == '/api/chan':
                candidate_flag = query.get('candidates', ['0'])[0]
                if candidate_flag not in ('0', '1'):
                    raise ValueError('invalid candidates parameter')
                result = chan_for_market(self.server.market, query.get('code', [''])[0], end,
                                         include_candidates=candidate_flag == '1')
            elif parsed.path == '/api/prices':
                context_flag = query.get('context', ['0'])[0]
                if context_flag not in ('0', '1'):
                    raise ValueError('invalid context parameter')
                result = self.server.market.candles(query.get('code', [''])[0], end, query.get('cycle', ['day'])[0], int(query.get('period', ['60'])[0]), query.get('start', [None])[0], **({'include_context': True} if context_flag == '1' else {}))
            elif parsed.path == '/api/research':
                result = self.server.market.research(end)
            elif parsed.path == '/api/review':
                result = self.server.market.review(query.get('code', [''])[0], query.get('observed', [''])[0], end)
            else:
                return self.send(404, {'error': '未找到'})
            self.send(200, result)
        except BatchError as e:
            self.send(400, {'error': str(e)})
        except DataError as e:
            self.send(502, {'error': str(e), **({'reason': e.reason} if e.reason else {})})
        except (ValueError, KeyError, IndexError):
            self.send(400, {'error': '参数或上游数据格式无效'})
        except Exception:
            self.send(500, {'error': '服务异常，请稍后重试'})


def is_address_in_use(error):
    # POSIX EADDRINUSE (98). Windows sockets use WSAEADDRINUSE (10048) if that error appears.
    codes = (errno.EADDRINUSE, getattr(errno, 'WSAEADDRINUSE', 10048))
    return getattr(error, 'errno', None) in codes or getattr(error, 'winerror', None) in codes


def port_in_use_message(port, demo=False):
    example = port + 1 if port < 65535 else 8766
    command = 'python3 server.py'
    if demo:
        command += ' --demo'
    command += f' --port {example}'
    return (
        f'端口 {port} 已被占用，无法启动。\n'
        f'请换一个端口后再试，例如：\n'
        f'{command}'
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--demo',action='store_true',help='只读合成演示，不读取密钥、不联网')
    args = parser.parse_args()
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    except OSError as error:
        if not is_address_in_use(error):
            raise
        print(port_in_use_message(args.port, args.demo), file=sys.stderr, flush=True)
        sys.exit(1)
    if args.demo:
        from demo import Demo
        server.demo=Demo()
    else:
        server.news = News(ROOT / 'data' / 'cache' / 'news')
        server.market = Market()
        server.tracking = Tracking(ROOT / 'data' / 'observations.sqlite3')
        server.rankings = Rankings(server.market)
        server.theme_clues = ThemeClues(server.market,server.rankings,AnnouncementClues(ROOT / 'data' / 'cache' / 'clue-announcements'))
        server.model = ModelService(ROOT / 'data' / 'model-config.json')
        server.disclosures = DisclosureStore(ROOT / 'data' / 'disclosures')
        server.analysis = Analysis(ROOT / 'data' / 'research.sqlite3',server.market,server.news,server.theme_clues,server.model,server.disclosures)
        server.batch = BatchService(server.analysis, ROOT / 'data' / 'batches.sqlite3')
        server.intraday = Intraday(ROOT / "data" / "cache" / "sina")
    print(f'看盘应用已启动：http://127.0.0.1:{args.port} （Ctrl+C 停止）', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
