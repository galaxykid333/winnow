import os
from pathlib import Path

import webview

from winnow.api import Api

DEBUG = os.environ.get('WINNOW_DEBUG') == '1'


def main():
    api = Api()
    root = Path(__file__).resolve().parent
    frontend = root / 'frontend' / 'index.html'
    icon = root / 'assets' / 'AppIcon.icns'
    # Passing a bare filesystem path here makes pywebview spin up a local
    # http://127.0.0.1 server to serve it (see webview/http.py). That's fine
    # for the page itself, but every <img src="file://..."> we point at the
    # cache (cache.py) or the source library then becomes a cross-scheme
    # request from an http: document to a file: resource, which WebKit
    # blocks outright — silently: no exception, no console output unless
    # you open the inspector. Passing an explicit file:// URI instead makes
    # pywebview load the page via file:// directly, under which file://
    # subresources from anywhere on disk load normally. Confirmed with a
    # minimal pywebview repro before applying this.
    webview.create_window(
        'Winnow',
        url=frontend.as_uri(),
        js_api=api,
        width=1280,
        height=900,
        min_size=(800, 600),
        background_color='#131519',
    )
    webview.start(debug=DEBUG, icon=str(icon))  # WINNOW_DEBUG=1 python3 main.py -> right-click -> Inspect Element


if __name__ == '__main__':
    main()
