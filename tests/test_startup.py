"""Startup bind errors: occupied ports get a Chinese hint; other failures are unchanged."""
import contextlib
import errno
import io
import json
import socket
import subprocess
import sys
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

import server

ROOT = Path(__file__).resolve().parents[1]


def occupy(host='127.0.0.1'):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, 0))
    sock.listen(1)
    return sock, sock.getsockname()[1]


class StartupTests(unittest.TestCase):
    def stop(self, proc):
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
        finally:
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()

    def run_server(self, *args, timeout=8):
        return subprocess.run(
            [sys.executable, '-B', str(ROOT / 'server.py'), *args],
            cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8', timeout=timeout,
        )

    def start_server(self, *args):
        proc = subprocess.Popen(
            [sys.executable, '-B', str(ROOT / 'server.py'), *args],
            cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
        )
        self.addCleanup(self.stop, proc)
        return proc

    def get(self, port, path):
        conn = HTTPConnection('127.0.0.1', port, timeout=2)
        try:
            conn.request('GET', path)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def wait_ready(self, port, proc, timeout=8):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                stdout, stderr = proc.communicate()
                raise AssertionError(f'server exited {proc.returncode}: {stdout}\n{stderr}')
            try:
                status, body = self.get(port, '/api/health')
                if status == 200:
                    return body
            except (OSError, json.JSONDecodeError, ValueError) as error:
                last = error
            time.sleep(0.05)
        raise AssertionError(f'demo server on port {port} did not start: {last}')

    def test_occupied_port_prints_chinese_hint_without_traceback(self):
        holder, port = occupy()
        self.addCleanup(holder.close)
        result = self.run_server('--demo', '--port', str(port))
        text = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1)
        self.assertIn(f'端口 {port} 已被占用', text)
        self.assertIn('--port', text)
        self.assertIn(str(port + 1 if port < 65535 else 8766), text)
        self.assertNotIn('Traceback', text)
        self.assertNotIn('Address already in use', text)

    def test_free_port_starts_demo_health_and_runtime(self):
        holder, port = occupy()
        holder.close()
        proc = self.start_server('--demo', '--port', str(port))
        health = self.wait_ready(port, proc)
        self.assertEqual(health.get('status'), 'ok')
        status, runtime = self.get(port, '/api/runtime')
        self.assertEqual(status, 200)
        self.assertEqual(runtime['mode'], 'demo')
        self.assertTrue(runtime['read_only'])
        self.assertTrue(runtime['synthetic'])
        self.stop(proc)
        self.assertIsNotNone(proc.returncode)
        self.assertTrue(proc.stdout.closed)
        self.assertTrue(proc.stderr.closed)

    def test_cleanup_closes_pipes_for_already_exited_child(self):
        holder, port = occupy()
        self.addCleanup(holder.close)
        proc = self.start_server('--demo', '--port', str(port))
        self.assertEqual(proc.wait(timeout=8), 1)
        self.stop(proc)
        self.assertTrue(proc.stdout.closed)
        self.assertTrue(proc.stderr.closed)

    def test_other_oserror_is_not_reported_as_port_in_use(self):
        error = OSError(errno.EACCES, 'Permission denied')
        with patch('server.ThreadingHTTPServer', side_effect=error), patch('sys.argv', ['server.py', '--demo', '--port', '8765']):
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                with self.assertRaises(OSError) as caught:
                    server.main()
        self.assertIs(caught.exception, error)
        self.assertEqual(caught.exception.errno, errno.EACCES)
        text = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn('已被占用', text)
        self.assertNotIn('换一个端口', text)

    def test_non_oserror_is_not_swallowed(self):
        with patch('server.ThreadingHTTPServer', side_effect=RuntimeError('synthetic bind failure')), patch('sys.argv', ['server.py', '--port', '8765']):
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                with self.assertRaises(RuntimeError):
                    server.main()
        self.assertNotIn('已被占用', stdout.getvalue() + stderr.getvalue())

    def test_address_in_use_recognizes_posix_and_windows_codes(self):
        self.assertTrue(server.is_address_in_use(OSError(errno.EADDRINUSE, 'Address already in use')))
        self.assertTrue(server.is_address_in_use(OSError(10048, 'Address already in use')))
        win = OSError('Address already in use')
        win.winerror = 10048
        self.assertTrue(server.is_address_in_use(win))
        self.assertFalse(server.is_address_in_use(OSError(errno.EACCES, 'Permission denied')))
        self.assertFalse(server.is_address_in_use(OSError('unrelated')))
        self.assertFalse(server.is_address_in_use(RuntimeError('no errno')))
