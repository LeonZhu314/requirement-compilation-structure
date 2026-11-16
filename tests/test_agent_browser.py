import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from infrastructure.runtime.artifacts import ArtifactStore
from infrastructure.runtime.browser import BrowserSession, LoopbackProxy


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_proxy_refuses_external_and_unowned_loopback_connections(self):
        proxy = LoopbackProxy(lambda: {3000})
        address = await proxy.start()
        try:
            reader, writer = await asyncio.open_connection('127.0.0.1', int(address.rsplit(':', 1)[1]))
            writer.write(b'\x05\x01\x00')
            await writer.drain()
            self.assertEqual(await reader.readexactly(2), b'\x05\x00')
            writer.write(b'\x05\x01\x00\x01\x7f\x00\x00\x01\x00\x50')
            await writer.drain()
            self.assertEqual((await reader.readexactly(10))[1], 2)
            writer.close()
            await writer.wait_closed()
            self.assertFalse(proxy.permitted('example.com', 3000))
            self.assertFalse(proxy.permitted('127.0.0.2', 3000))
        finally:
            await proxy.aclose()


class RealBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_form_network_failure_fix_reload_and_screenshot_in_one_browser(self):
        with TemporaryDirectory() as tmp:
            state = {'broken': True, 'saved': [], 'requests': [], 'forbidden': 0}
            html = '''<html><body><label>Title<input aria-label="Title"></label><button>Save</button>
            <p role="status">Ready</p><script>document.querySelector('button').onclick=async()=>{
              const r=await fetch('/save',{method:'POST',body:document.querySelector('input').value});
              document.querySelector('[role=status]').textContent=r.ok?'Saved':'Failed';
            };</script></body></html>'''
            async def handle(reader, writer):
                try:
                    headers = await reader.readuntil(b'\r\n\r\n')
                    first = headers.splitlines()[0].decode()
                    state['requests'].append(first)
                    length = next((int(line.split(b':', 1)[1]) for line in headers.splitlines()
                        if line.lower().startswith(b'content-length:')), 0)
                    body = await reader.readexactly(length)
                    if first.startswith('POST /save '):
                        status, content, mime = (500 if state['broken'] else 200), b'{}', 'application/json'
                        if status == 200:
                            state['saved'].append(body.decode())
                    elif first.startswith('GET /redirect '):
                        writer.write(f'HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:{forbidden_port}/private\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'.encode())
                        await writer.drain()
                        return
                    else:
                        status, content, mime = 200, html.encode(), 'text/html'
                    writer.write(f'HTTP/1.1 {status} Response\r\nContent-Type: {mime}\r\nContent-Length: {len(content)}\r\nConnection: close\r\n\r\n'.encode() + content)
                    await writer.drain()
                except (OSError, asyncio.IncompleteReadError):
                    pass
                finally:
                    writer.close()
                    await writer.wait_closed()
            async def forbidden(reader, writer):
                state['forbidden'] += 1
                writer.close()
                await writer.wait_closed()
            server = await asyncio.start_server(handle, '127.0.0.1', 0)
            guard = await asyncio.start_server(forbidden, '127.0.0.1', 0)
            port, forbidden_port = server.sockets[0].getsockname()[1], guard.sockets[0].getsockname()[1]
            class Services:
                def ports(self):
                    return {port}
            browser = BrowserSession(Services(), ArtifactStore(Path(tmp)))
            try:
                from playwright.async_api import async_playwright
                async with async_playwright() as driver:
                    if not Path(driver.chromium.executable_path).is_file():
                        self.skipTest('Install Chromium to run the real browser integration')
                await browser.action('open', url=f'http://127.0.0.1:{port}/')
                page = browser.page
                await browser.action('fill', role='textbox', name='Title', value='A note')
                await browser.action('click', role='button', name='Save')
                await page.get_by_role('status').filter(has_text='Failed').wait_for()
                self.assertTrue(any('500' in item['text'] for item in browser.logs))
                state['broken'] = False
                await browser.action('open', url=f'http://127.0.0.1:{port}/')
                await browser.action('fill', role='textbox', name='Title', value='A note')
                await browser.action('click', role='button', name='Save')
                await page.get_by_role('status').filter(has_text='Saved').wait_for()
                self.assertIs(browser.page, page)
                self.assertEqual(state['saved'], ['A note'])
                result = await browser.action('screenshot')
                self.assertTrue(browser.artifacts.path(result['screenshot']).is_file())
                self.assertIn('Saved', result['dom'])
                with self.assertRaises(Exception):
                    await browser.action('open', url=f'http://127.0.0.1:{port}/redirect')
                self.assertEqual(state['forbidden'], 0)
            finally:
                await browser.aclose()
                for listener in (server, guard):
                    listener.close()
                    await listener.wait_closed()
