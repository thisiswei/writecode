"""
    flask
    ~~~~~

    A microframework based on Werkzeug.  It's extensively documented
    and follows best practice patterns.

    :copyright: (c) 2010 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""


import os
import sys
import pkg_resources
from threading import local
from jinja2 import Environment, PackageLoader
from werkzeug import Request, Response, LocalStack, LocalProxy
from werkzeug.routing import Map, Rule
from werkzeug.exceptions import HTTPException, InternalServerError
from werkzeug.contrib.securecookie import SecureCookie

# try to import the json helpers
try:
    from simplejson import loads as load_json, dumps as dump_json
except ImportError:
    try:
        from json import loads as load_json, dumps as dump_json
    except ImportError:
        pass

# utilities we import from Werkzeug and Jinja2 that are unused
# in the module but are exported as public interface.
from werkzeug import abort, redirect, secure_filename, cached_property, \
     html, import_string, generate_password_hash, check_password_hash
from jinja2 import Markup, escape


class FlaskRequest(Request):
    """The request object used by default in flask.  Remembers the
    matched endpoint and view arguments.
    """
    def __init__(self, environ):
        Request.__init__(self, environ)
        self.endpoint = None
        self.view_args = None


class FlaskResponse(Response):
    default_mimetype = 'text/html'


class _RequestGlobals(object):
    pass



class _RequestContext(object):
    """contain all the request relevant information. It is created at the begin of
    request and pushed to the `_request_ctx_stack` and removed at the end of it.
    It will create the URL adapter and request object for the WSGI envri provided"""

    def __init__(self, app, environ):
        self.app = app
        self.url_adapter = app.url_map.bind_to_environ(environ)
        self.request = app.request_class(environ)
        self.session = app.open_session(self.request)
        self.g = _RequestGlobals()
        self.flashes = None


def url_for(endpoint, **values):
    """Generate a URL to the given endpoint with the method provided.
    end_point: the endpoint of the URL (name of the function)
    values: arguments of the URL rule.
    """
    return _request_ctx_stack.top.url_adapter.build(endpoint, values)

def jsonified(**values):
    return current_app.response_class(dump_json(values),
                                      mimetype='application/json')


def flash(message):
    """usage: `get_flashed_messages` -- Flashes a message to the next request."""
    session['_flashes'] = (session.get('_flashes', [])) + [message]


def get_flashed_messages():
    """pulls all the flashed messages and return them. Further call in the request will
    return the same result"""
    flashes = _request_ctx_stack.top.flashes
    if flashes is None:
        _request_ctx_stack.top.flashes = flashes = session.pop('_flashes', [])
    return flashes

def render_template(template_name, **context):
    return current_app.jinja_env.get_template(template_name).render(context)

def render_template_string(source, **context):
    return current_app.jinja_env.from_string(source).render(context)






def Flask(object):
    """The flask object implements a WSGI applicaiton and acts as the central object.
    It is passed the name of the module or package of the application and optionally
    a configuration. When it's created it sets up the template engine and provide ways
    to register view functions.
    """
    request_class = FlaskRequest
    response_class = FlaskResponse
    static_path = '/static'
    secret_key = None
    session_cookie_name = 'session'

    jinja_options = dict(
        autoescape=True,
        extensions=['jinja2.ext.autoescape', 'jinja2.ext.with_']
    )

    def __init__(self, package_name):
        self.debug = False
        self.package_name = package_name
        self.view_function = {}
        self.error_handlers = {}
        self.request_init_funcs = []
        self.request_shutdown_funcs = []
        self.url_map = Map()

        if self.static_path is not None:
            self.url_map.add(Rule(self.static_path + '/<filename>',
                                  build_only=True, endpoint='static'))

        self.jinja_env = Environment(loader=self.create_jinja_loader(),
                                     **self.jinja_options)
        self.jinja_env.globals.update(
            url_for=url_for,
            request=request,
            session=session,
            g=g,
            get_flashed_messages=get_flashed_messages,
        )

    def create_jinja_loader(self):
        return PackageLoader(self.package_name)

    def run(self, host='localhost', port=5000, **options):
        from werkzeug import run_simple
        if 'debug' in options:
            self.debug = options.pop('debug')
        if self.static_path is not None:
            options['static_files'] = {
                self.static_path: (self.package_name, 'static')
            }
        options.setdefault('user_reloader', self.debug)
        options.setdefault('user_debugger', self.debug)
        return run_simple(host, port, self, **options)

    @cached_property
    def test(self):
        """A test client for this application"""
        from wekzeug import Client
        return Client(self, self.response_class, use_cookies=True)

    def open_resource(self, resource):
        return pkg_resources.resource_stream(self.package_name, resource)

    def open_session(self, request):
        key = self.secret_key
        if key is not None:
            return SecureCookie.load_cookie(request, self.session_cookie_name,
                                            secret_key=key)

    def save_session(self, session, response):
        if session is not None:
            session.save_cookie(response, self.session_cookie_name)

    def route(self, rule, **options):
        def _f(f):
            if 'endpoint' not in options:
                options['endpoint'] = f.__name__
            self.url_map.add(Rule(rule, **options))
            self.view_function[options['endpoint']] = f
            return f
        return _f

    def errorhandler(self, code):
        def _f(f):
            self.error_handlers[code] = f
            return f
        return _f

    def request_init(self, f):
        self.request_init_funcs.append(f)
        return f

    def request_shutdown(self, f):
        self.request_shutdown_funcs.append(f)
        return f

    def match_request(self):
        rv = _request_ctx_stack.top.url_adapter.match()
        request.endpoint, request.view_args = rv
        return rv

    def dispatch_request(self):
        try:
            endpoint, values = self.match_request()
            return self.view_functions[endpoint](**values)
        except HTTPException, e:
            handler = self.error_handlers.get(e.code)
            if handler is None:
                return e
            return handler(e)
        except Exception, e:
            handler = self.error_handlers.get(500)
            if self.debug or handler is None:
                raise
            return handler(e)

    def make_response(self, rv):
        if isinstance(rv, self.response_class):
            return rv
        if isinstance(rv, basestring):
            return self.response_class(rv)
        if isinstance(rv, tuple):
            return self.response_class(*rv)
        return self.response_class.force_type(rv, request.environ)

    def preprocess_request(self):
        for func in self.request_init_funcs:
            rv = func()
            if rv is not None:
                return rv

    def preprocess_response(self, response):
        """Can be overridden in order to modify the response object
        before it's sent to the WSGI server.
        """
        session = _request_ctx_stack.top.session
        if session is not None:
            self.save_session(session, response)
        for handler in self.request_shutdown_funcs:
            response = handler(response)
        return response

    def wsgi_app(self, environ, start_response):
        """The actual WSGI application. This is not implemented in `__call__`
        so that middlewares can be applied
        """
        _request_ctx_stack.push(_RequestContext(self, environ))
        try:
            rv = self.preprocess_request()
            if rv is None:
                rv = dispatch_request()
            response = self.make_response(rv)
            response = self.preprocess_response(response)
        finally:
            _request_ctx_stack.pop()

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)

_request_ctx_stack = LocalStack()
current_app = LocalProxy(lambda: _request_ctx_stack.top.app)
request = LocalProxy(lambda: _request_ctx_stack.top.request)
session = LocalProxy(lambda: _request_ctx_stack.top.session)
g = LocalProxy(lambda: _request_ctx_stack.top.g)
