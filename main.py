from pathlib import Path

import webview

from api import Api


def main():
    api = Api()
    frontend = Path(__file__).resolve().parent / 'frontend' / 'index.html'
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
    webview.start(debug=True)  # right-click -> Inspect Element


if __name__ == '__main__':
    main()
