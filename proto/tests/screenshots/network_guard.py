"""Offline browser audit: only the configured application origin may use the network."""
from urllib.parse import urlsplit


def is_local_url(base: str, url: str) -> bool:
    target, app = urlsplit(url), urlsplit(base)
    if target.scheme in ('data', 'blob'):
        return True  # browser-local resources do not contact a host
    if target.scheme not in ('http', 'https', 'ws', 'wss'):
        return False
    try:
        target_port = target.port or (443 if target.scheme in ('https', 'wss') else 80)
        app_port = app.port or (443 if app.scheme == 'https' else 80)
    except ValueError:
        return False
    target_secure = target.scheme in ('https', 'wss')
    return (target.hostname == app.hostname and target_port == app_port
            and target_secure == (app.scheme == 'https') and target.username is None)


def install(context, base: str, external: list, active):
    """Attach HTTP and WebSocket interception before creating a page; abort every external attempt."""
    def record(url, kind):
        bucket = active()
        if kind == 'websocket':
            bucket['websockets'].append(url)
        if not is_local_url(base, url):
            item = {'route': bucket['route'], 'viewport': bucket['viewport'], 'kind': kind, 'url': url}
            external.append(item)
            bucket['external_requests'].append(item)
            return False
        if kind == 'http':
            bucket['local_request_count'] += 1
        return True

    def http(route, request):
        if record(request.url, 'http'):
            route.continue_()
        else:
            route.abort()

    def websocket(route):
        if record(route.url, 'websocket'):
            route.connect_to_server()
        else:
            route.close(code=1008, reason='external network forbidden by offline acceptance gate')

    context.route('**/*', http)
    context.route_web_socket('**/*', websocket)


def bucket(route, viewport):
    return {'route': route, 'viewport': viewport, 'local_request_count': 0,
            'external_requests': [], 'websockets': []}
