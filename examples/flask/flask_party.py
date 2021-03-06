# pip install Flask

import copy

from flask import Flask, abort, request
from werkzeug.routing import BuildError
from werkzeug.urls import url_quote
from wsgi_party import WSGIParty, HighAndDry


class PartylineFlask(Flask):
    def __init__(self, import_name, *args, **kwargs):
        super(PartylineFlask, self).__init__(import_name, *args, **kwargs)
        self.add_url_rule(WSGIParty.invite_path, endpoint='partyline',
                          view_func=self.join_party)
        self.partyline = None
        self.connected = False

    def join_party(self, request=request):
        # Bootstrap, turn the view function into a 404 after registering.
        if self.connected:
            # This route does not exist at the HTTP level.
            abort(404)
        self.partyline = request.environ.get(WSGIParty.partyline_key)
        self.partyline.connect('ping', lambda x: 'pong')
        self.partyline.connect('url', self.handle_url)
        self.connected = True
        return 'ok'

    def handle_url(self, payload):
        endpoint, values = payload
        try:
            return self.my_url_for(endpoint, **values)
        except BuildError:
            raise HighAndDry()

    def url_for(self, endpoint, use_partyline=True, **values):
        """Build a URL, asking other applications if BuildError occurs locally.

        This implementation is a fork of :func:`~flask.helpers.url_for`, where
        the implementation you see here works around Flask's context-locals to
        provide URL routing specific to ``self``.  Then it implements the
        wsgi_party url_for requests across Flask applications loaded into the
        dispatcher.
        """
        # Some values are popped; keep an original copy for re-requesting URL.
        copy_values = copy.deepcopy(values)
        blueprint_name = request.blueprint
        if endpoint[:1] == '.':
            if blueprint_name is not None:
                endpoint = blueprint_name + endpoint
            else:
                endpoint = endpoint[1:]
        external = values.pop('_external', False)
        anchor = values.pop('_anchor', None)
        method = values.pop('_method', None)
        self.inject_url_defaults(endpoint, values)
        url_adapter = self.create_url_adapter(request)
        try:
            rv = url_adapter.build(endpoint, values, method=method,
                                   force_external=external)
        except BuildError:
            # We do not have this URL, ask the partyline.
            if not use_partyline:
                raise
            for url in self.partyline.send_all('url', (endpoint, copy_values)):
                # First response wins.
                return url
        if anchor is not None:
            rv += '#' + url_quote(anchor)
        return rv

    def my_url_for(self, endpoint, **values):
        """Context-locals hurt."""
        with self.test_request_context():
            return self.url_for(endpoint, use_partyline=False, **values)


# Demonstrate.
root = PartylineFlask(__name__)
one = PartylineFlask(__name__)
two = PartylineFlask(__name__)

root.debug = True
one.debug = True
two.debug = True

one.config['APPLICATION_ROOT'] = '/one'
two.config['APPLICATION_ROOT'] = '/two'

template = """
<html>
<head>
  <title>Demo: Cross-application URL building in Flask.</title>
</head>
<body>
  <p>You are in the root application.</p>
  <ul>
    <li><a href="%s">Go to application one</a></li>
    <li><a href="%s">Go to application two</a></li>
  </ul>
  <p>Source code is <a href="http://github.com/rduplain/wsgi_party">here</a>.</p>
</body>
</html>
"""

@root.route('/', endpoint='index')
def root_index():
    if not root.partyline:
        return 'I have no friends.'
    return template % (root.url_for('one:index'), root.url_for('two:index'))

@one.route('/', endpoint='one:index')
def one_index():
    url = one.url_for('two:index')
    return 'This is app one. <a href="%s">Go to two.</a>' % url

@two.route('/', endpoint='two:index')
def two_index():
    url = two.url_for('one:index')
    return 'This is app two. <a href="%s">Go to one.</a>' % url

application = WSGIParty(root, {
    '/one': one,
    '/two': two,
})


if __name__ == '__main__':
    import os
    from werkzeug.serving import run_simple
    # Bind to PORT if defined, otherwise default to 5000.
    port = int(os.environ.get('PORT', 5000))
    run_simple('0.0.0.0', port, application, use_reloader=True)
