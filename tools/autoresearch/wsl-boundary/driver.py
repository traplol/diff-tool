"""Drive the real Windows WebView2 or Linux WebKit Branchline interface.

Windows: expose WebView2's loopback CDP port through an SSH local forward, then
attach with --cdp http://127.0.0.1:19223. Never expose the debug port to the LAN.
Linux: attach to an existing WebKitWebDriver session using --webkit-port and
--session. The Linux transport reuses tools/smoke_native.py.

Timing belongs in injected browser code. Host polling and SSH round trips are
not interaction timing, and a cleared busy flag alone does not prove a comment
jump finished. Require the expected visible content before resolving a sample.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import runpy
import time
from urllib import error, request
from urllib.parse import urlparse


class BrowserDriver:
    def evaluate(self, body: str, *args):
        """Run an async JavaScript function body; arguments are JSON values."""
        raise NotImplementedError

    def wait(self, condition: str, *args, timeout: float = 30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.evaluate(f"return ({condition});", *args)
            if value:
                return value
            time.sleep(0.025)
        raise TimeoutError(f"Browser condition did not become true: {condition}")

    def select(self, selector: str, value: str):
        # Both engines dispatch the same product change handler. A benchmark
        # starts its browser timer on that change event, not on host RPC start.
        return self.evaluate("""
            const element = document.querySelector(arguments[0]);
            if (!element || element.disabled || element.tagName !== 'SELECT')
                throw Error('Unavailable select: ' + arguments[0]);
            const value = String(arguments[1]);
            if (![...element.options].some(option => option.value === value))
                throw Error('Missing select value: ' + value);
            element.value = value;
            element.dispatchEvent(new Event('change', {bubbles:true}));
        """, selector, value)

    def info(self):
        return self.evaluate("""
            return {
                url: location.href,
                title: document.title,
                user_agent: navigator.userAgent,
                viewport: [innerWidth, innerHeight],
                visible: document.visibilityState,
                busy: document.querySelector('#app')?.hasAttribute('aria-busy'),
                repository: document.querySelector('#repo-path')?.textContent,
                comparison: document.querySelector('#range')?.textContent,
                filename: document.querySelector('#filename')?.textContent,
                status: document.querySelector('footer')?.textContent,
            };
        """)


class CdpDriver(BrowserDriver):
    def __init__(self, endpoint: str, *, timeout: float = 180):
        parsed = urlparse(endpoint)
        if parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}:
            raise ValueError('Use a loopback CDP endpoint through an SSH forward')
        if parsed.scheme != 'http':
            raise ValueError('Expected an http:// loopback CDP endpoint')
        try:
            import websocket
        except ImportError as error:
            raise RuntimeError('Windows CDP requires Python websocket-client') from error
        with request.urlopen(endpoint.rstrip('/') + '/json/list', timeout=timeout) as response:
            targets = json.load(response)
        pages = [target for target in targets if target.get('type') == 'page'
                 and target.get('webSocketDebuggerUrl')]
        matches = [target for target in pages
                   if 'tauri.localhost' in target.get('url', '')
                   or 'Branchline' in target.get('title', '')]
        if len(matches) != 1:
            raise RuntimeError(f'Expected one Branchline WebView2 page, found {len(matches)}')
        target = matches[0]
        target_url = urlparse(target['webSocketDebuggerUrl'])
        # Chromium reports its guest-local port. The SSH forward can have a
        # different host port, so retain the observed path but use our endpoint.
        websocket_url = 'ws://' + parsed.netloc + target_url.path
        if target_url.query:
            websocket_url += '?' + target_url.query
        self.socket = websocket.create_connection(
            websocket_url,
            timeout=timeout,
            suppress_origin=True,
            http_no_proxy=['127.0.0.1', 'localhost', '::1'],
        )
        self.timeout = timeout
        self.serial = 0

    def call(self, method: str, params=None):
        self.serial += 1
        serial = self.serial
        self.socket.send(json.dumps({'id': serial, 'method': method, 'params': params or {}}))
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f'CDP command timed out: {method}')
            self.socket.settimeout(remaining)
            message = json.loads(self.socket.recv())
            if message.get('id') != serial:
                continue
            if 'error' in message:
                raise RuntimeError(f"{method}: {message['error']}")
            return message.get('result', {})

    def evaluate(self, body: str, *args):
        result = self.call('Runtime.evaluate', {
            'expression': '(async function(){\n' + body + '\n}).apply(null,' + json.dumps(args) + ')',
            'awaitPromise': True,
            'returnByValue': True,
        })
        if details := result.get('exceptionDetails'):
            raise RuntimeError(details.get('exception', {}).get('description') or details.get('text'))
        value = result['result']
        if 'unserializableValue' in value:
            raise RuntimeError(f'JavaScript result is not JSON: {value["unserializableValue"]}')
        return value.get('value')

    def click(self, selector: str, text=None, exact: bool = True):
        point = self.evaluate("""
            const [selector, text, exact] = arguments;
            const element = [...document.querySelectorAll(selector)].find(element =>
                element.getClientRects().length && !element.disabled &&
                (text === null || (exact ? element.textContent.trim() === text
                    : element.textContent.includes(text))));
            if (!element) throw Error('Unavailable click target: ' + selector);
            element.scrollIntoView({block:'nearest', inline:'nearest'});
            const rect = element.getBoundingClientRect();
            const point = {x:rect.left + rect.width / 2, y:rect.top + rect.height / 2};
            const hit = document.elementFromPoint(point.x, point.y);
            if (!hit || !element.contains(hit)) throw Error('Click target is obscured');
            return point;
        """, selector, text, exact)
        self.call('Input.dispatchMouseEvent', {'type': 'mouseMoved', **point})
        for event in ('mousePressed', 'mouseReleased'):
            self.call('Input.dispatchMouseEvent', {
                'type': event, 'button': 'left', 'clickCount': 1, **point,
            })

    def screenshot(self, path: Path):
        result = self.call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False})
        Path(path).write_bytes(base64.b64decode(result['data']))

    def close(self):
        self.socket.close()


class WebKitDriver(BrowserDriver):
    def __init__(self, port: int, session: str, *, timeout: float = 180):
        source = Path(__file__).resolve().parents[2] / 'smoke_native.py'
        original = runpy.run_path(str(source))['Driver']
        self.driver = original(port)
        self.driver.session = '/session/' + session.removeprefix('/session/')
        self.timeout = timeout
        # Keep the existing input helpers, but allow a slow baseline interaction
        # to resolve in-browser instead of truncating it at the smoke rig's 35s.
        self.driver.call = self._call
        self.driver.call('POST', '/timeouts', {'script': round(timeout * 1000)})

    def _call(self, method, path, data=None):
        body = json.dumps(data).encode() if data is not None else None
        message = request.Request(
            self.driver.url + self.driver.session + path,
            method=method, data=body, headers={'Content-Type': 'application/json'},
        )
        try:
            with request.urlopen(message, timeout=self.timeout) as response:
                return json.load(response)['value']
        except error.HTTPError as exc:
            raise RuntimeError(f'{method} {path}: {exc.read().decode()}') from exc

    def evaluate(self, body: str, *args):
        result = self.driver.call('POST', '/execute/async', {
            'script': 'const args = [...arguments], done = args.pop(); '
                      '(async function(){\n' + body + '\n}).apply(null,args).then('
                      'value => done({ok:true,value:value ?? null}), '
                      'error => done({ok:false,error:String(error)}));',
            'args': list(args),
        })
        if not result['ok']:
            raise RuntimeError(result['error'])
        return result['value']

    def click(self, selector: str, text=None, exact: bool = True):
        # WebKit's element-click endpoint can report "not interactable" after
        # a tab click already changed the DOM. Dispatch the same pointer action
        # used by the native workflow checks, with an explicit visible hit test.
        x, y = self.evaluate("""
            const [selector, text, exact] = arguments;
            const element = [...document.querySelectorAll(selector)].find(element =>
                element.getClientRects().length && !element.disabled &&
                (text === null || (exact ? element.textContent.trim() === text
                    : element.textContent.includes(text))));
            if (!element) throw Error('Unavailable click target: ' + selector);
            element.scrollIntoView({block:'nearest', inline:'nearest'});
            const rect = element.getBoundingClientRect();
            const x = Math.round(rect.left + rect.width / 2);
            const y = Math.round(rect.top + rect.height / 2);
            if (!element.contains(document.elementFromPoint(x, y)))
                throw Error('Click target is obscured');
            return [x, y];
        """, selector, text, exact)
        self.driver.call('POST', '/actions', {'actions': [{
            'type': 'pointer', 'id': 'boundary-mouse',
            'parameters': {'pointerType': 'mouse'},
            'actions': [
                {'type': 'pointerMove', 'origin': 'viewport', 'x': x, 'y': y},
                {'type': 'pointerDown', 'button': 0},
                {'type': 'pointerUp', 'button': 0},
            ],
        }]})

    def screenshot(self, path: Path):
        Path(path).write_bytes(base64.b64decode(self.driver.call('GET', '/screenshot')))

    def close(self):
        # The caller owns the WebDriver session and process, just as it owns the
        # Windows app behind an attached CDP socket.
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    engine = parser.add_mutually_exclusive_group(required=True)
    engine.add_argument('--cdp', help='Loopback WebView2 debugging endpoint, usually an SSH forward')
    engine.add_argument('--webkit-port', type=int, help='Existing WebKitWebDriver port')
    parser.add_argument('--session', help='Existing WebKitWebDriver session id')
    parser.add_argument('--screenshot', type=Path)
    parser.add_argument('--timeout', type=float, default=180)
    args = parser.parse_args()
    if args.webkit_port and not args.session:
        parser.error('--webkit-port requires --session')
    driver = (CdpDriver(args.cdp, timeout=args.timeout) if args.cdp else
              WebKitDriver(args.webkit_port, args.session, timeout=args.timeout))
    try:
        print(json.dumps(driver.info(), indent=2))
        if args.screenshot:
            driver.screenshot(args.screenshot)
    finally:
        driver.close()


if __name__ == '__main__':
    main()
