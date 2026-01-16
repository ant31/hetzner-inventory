import functools
import json
import logging
import re
from base64 import b64encode

try:
    from httplib import BadStatusLine, ResponseNotReady
except ImportError:
    from http.client import BadStatusLine, ResponseNotReady

try:
    from urllib import urlencode
except ImportError:
    from urllib.parse import urlencode

from . import RobotError, WebRobotError
from .failover import FailoverManager
from .rdns import ReverseDNSManager
from .server import Server
from .util.http import ValidatedHTTPSConnection
from .vswitch import VswitchManager

ROBOT_HOST = "robot-ws.your-server.de"
ROBOT_WEBHOST = "robot.hetzner.com"
ROBOT_LOGINHOST = "accounts.hetzner.com"

RE_CSRF_TOKEN = re.compile(r'<input[^>]*?name="_csrf_token"[^>]*?value="([^">]+)"')

__all__ = ["Robot", "RobotConnection", "RobotWebInterface", "ServerManager"]


class RobotWebInterface:
    """
    This is for scraping the web interface and can be used to implement
    features that are not yet available in the official API.
    """

    def __init__(self, user=None, passwd=None):
        self.conn = None
        self.session_cookie = None
        self.user = user
        self.passwd = passwd
        self.logged_in = False
        self.logger = logging.getLogger(f"Robot scraper for {user}")

    def _parse_cookies(self, response):
        """
        Return a dictionary consisting of the cookies from the given response.
        """
        result = {}
        cookies = response.getheader("set-cookie")
        if cookies is None:
            return result

        # Not very accurate but sufficent enough for our use case.
        for cookieval in cookies.split(","):
            cookieattrs = cookieval.strip().split(";")
            if len(cookieattrs) <= 1:
                continue
            cookie = cookieattrs[0].strip().split("=", 1)
            if len(cookie) != 2:
                continue
            result[cookie[0]] = cookie[1]

        return result

    def update_session(self, response):
        """
        Parses the session cookie from the given response instance and updates
        self.session_cookie accordingly if a session cookie was recognized.
        """
        session = self._parse_cookies(response).get("robot")
        if session is not None:
            self.session_cookie = "robot=" + session

    def connect(self, force=False):
        """
        Establish a connection to the robot web interface if we're not yet
        connected. If 'force' is set to True, throw away the old connection and
        establish a new one, regardless of whether we are connected or not.
        """
        if force and self.conn is not None:
            self.conn.close()
            self.conn = None
        if self.conn is None:
            self.conn = ValidatedHTTPSConnection(ROBOT_WEBHOST)

    def _get_auth_url(self):
        """Get the OAuth authentication URL from Robot."""
        self.logger.debug("Visiting Robot web frontend for the first time.")
        auth_url = self.request("/", xhr=False).getheader("location")

        if not auth_url.startswith("https://" + ROBOT_LOGINHOST + "/"):
            msg = "https://{0}/ does not redirect to https://{1}/ but instead redirects to: {2}"
            raise WebRobotError(msg.format(ROBOT_WEBHOST, ROBOT_LOGINHOST, auth_url))

        self.logger.debug("Following authentication redirect to %r.", auth_url)
        return auth_url

    def _get_session_cookie(self, auth_url):
        """Get initial session cookie from auth site."""
        login_conn = ValidatedHTTPSConnection(ROBOT_LOGINHOST)
        login_conn.request("GET", auth_url[len(ROBOT_LOGINHOST) + 8 :], None)

        response = login_conn.getresponse()
        if response.status != 302:
            raise WebRobotError(f"Invalid status code {response.status} while visiting auth URL")

        cookies = self._parse_cookies(response)
        if "PHPSESSID" not in cookies:
            raise WebRobotError("Auth site didn't respond with a session cookie.")

        self.logger.debug("Session ID for auth site is %r.", cookies["PHPSESSID"])
        return cookies

    def _get_csrf_token(self, headers):
        """Get CSRF token from login page."""
        self.logger.debug("Visiting login page at https://%s/login.", ROBOT_LOGINHOST)
        login_conn = ValidatedHTTPSConnection(ROBOT_LOGINHOST)
        login_conn.request("GET", "/login", None, headers)

        response = login_conn.getresponse()
        if response.status != 200:
            raise WebRobotError(f"Invalid status code {response.status} while visiting login page")

        haystack = response.read()
        token = RE_CSRF_TOKEN.search(str(haystack))
        if token is None:
            raise WebRobotError("Unable to find CSRF token for login form")
        return token.group(1)

    def _perform_login(self, headers, csrf_token):
        """Perform the actual login with credentials."""
        data = urlencode({"_username": self.user, "_password": self.passwd, "_csrf_token": csrf_token})
        self.logger.debug("Logging in to auth site with user %s.", self.user)

        login_conn = ValidatedHTTPSConnection(ROBOT_LOGINHOST)
        post_headers = headers.copy()
        post_headers["Content-Type"] = "application/x-www-form-urlencoded"
        login_conn.request("POST", "/login_check", data, post_headers)
        response = login_conn.getresponse()

        cookies = self._parse_cookies(response)
        if "PHPSESSID" not in cookies:
            raise WebRobotError("Login to robot web interface failed.")
        self.logger.debug("New session ID for auth site after login is %r.", cookies["PHPSESSID"])
        return cookies

    def _get_oauth_url(self, headers):
        """Get OAuth authorization URL after login."""
        location = headers.getheader("Location")
        if headers.status != 302 or location is None:
            raise WebRobotError("Unable to get OAuth authorization URL.")

        if not location.startswith("https://" + ROBOT_LOGINHOST + "/"):
            msg = "https://{0}/ does not redirect to https://{1}/ but instead redirects to: {2}"
            raise WebRobotError(msg.format(ROBOT_LOGINHOST, ROBOT_LOGINHOST, location))

        self.logger.debug("Got redirected, visiting %r.", location)
        return location

    def _complete_oauth_flow(self, oauth_url, headers):
        """Complete OAuth flow and return to Robot."""
        login_conn = ValidatedHTTPSConnection(ROBOT_LOGINHOST)
        login_conn.request("GET", oauth_url[len(ROBOT_LOGINHOST) + 8 :], None, headers)
        response = login_conn.getresponse()

        location = response.getheader("Location")
        if response.status != 302 or location is None:
            raise WebRobotError("Failed to get OAuth URL for Robot.")
        if not location.startswith("https://" + ROBOT_WEBHOST + "/"):
            msg = "https://{0}/ does not redirect to https://{1}/ but instead redirects to: {2}"
            raise WebRobotError(msg.format(ROBOT_LOGINHOST, ROBOT_WEBHOST, location))

        self.logger.debug("Going back to Robot web interface via %r.", location)
        return location

    def _finalize_login(self, robot_url):
        """Finalize login by connecting to Robot with OAuth token."""
        self.connect(force=True)
        response = self.request(robot_url[len(ROBOT_WEBHOST) + 8 :], xhr=False)

        if response.status != 302:
            raise WebRobotError(f"Status after providing OAuth token should be 302 and not {response.status}")

        if response.getheader("location") != "https://" + ROBOT_WEBHOST + "/":
            raise WebRobotError("Robot login with OAuth token has failed.")

    def login(self, user=None, passwd=None, force=False):
        """
        Log into the robot web interface using self.user and self.passwd. If
        user/passwd is provided as arguments, those are used instead and
        self.user/self.passwd are updated accordingly.
        """
        if self.logged_in and not force:
            return

        self.connect(force=force)

        if user is not None:
            self.user = user
        if passwd is not None:
            self.passwd = passwd

        if self.user is None or self.passwd is None:
            raise WebRobotError("Login credentials for the web user interface are missing.")

        if self.user.startswith("#ws+"):
            raise WebRobotError(
                f"The user {self.user} is a dedicated web service user "
                "and cannot be used for scraping the web user interface."
            )

        auth_url = self._get_auth_url()
        cookies = self._get_session_cookie(auth_url)

        cookieval = "; ".join([k + "=" + v for k, v in cookies.items()])
        headers = {"Cookie": cookieval}

        csrf_token = self._get_csrf_token(headers)
        cookies = self._perform_login(headers, csrf_token)

        cookieval = "; ".join([k + "=" + v for k, v in cookies.items()])
        headers["Cookie"] = cookieval

        login_conn = ValidatedHTTPSConnection(ROBOT_LOGINHOST)
        login_conn.request("POST", "/login_check", "", headers)
        response = login_conn.getresponse()

        oauth_url = self._get_oauth_url(response)
        robot_url = self._complete_oauth_flow(oauth_url, headers)
        self._finalize_login(robot_url)

        self.logged_in = True

    def request(self, path, data=None, xhr=True, method=None, log=True):
        """
        Send a request to the web interface, using 'data' for urlencoded POST
        data. If 'data' is None (which it is by default), a GET request is sent
        instead. A httplib.HTTPResponse is returned on success.

        By default this method uses headers for XMLHttpRequests, so if the
        request should be an ordinary HTTP request, set 'xhr' to False.

        If 'log' is set to False, don't log anything containing data. This is
        useful to prevent logging sensible information such as passwords.
        """
        self.connect()

        headers = {"Connection": "keep-alive"}
        if self.session_cookie is not None:
            headers["Cookie"] = self.session_cookie
        if xhr:
            headers["X-Requested-With"] = "XMLHttpRequest"

        if data is None:
            if method is None:
                method = "GET"
            encoded = None
        else:
            if method is None:
                method = "POST"
            encoded = urlencode(data)
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        if log:
            self.logger.debug(
                "Sending %s request to Robot web frontend at %s with data %r.",
                ("XHR " if xhr else "") + method,
                path,
                encoded,
            )
        self.conn.request(method, path, encoded, headers)

        try:
            response = self.conn.getresponse()
        except ResponseNotReady:
            self.logger.debug("Connection closed by Robot web frontend, retrying.")
            # Connection closed, so we need to reconnect.
            # FIXME: Try to avoid endless loops here!
            self.connect(force=True)
            return self.request(path, data=data, xhr=xhr, log=log)

        if log:
            self.logger.debug("Got response from web frontend with status %d.", response.status)

        self.update_session(response)
        return response


class RobotConnection:
    def __init__(self, user, passwd):
        self.user = user
        self.passwd = passwd
        self.conn = ValidatedHTTPSConnection(ROBOT_HOST)
        self.logger = logging.getLogger(f"Robot of {user}")

        # Provide this as a way to easily add unsupported API features.
        self.scraper = RobotWebInterface(user, passwd)

    def _request(self, method, path, data, headers, retry=1):
        self.conn.request(method.upper(), path, data, headers)
        try:
            return self.conn.getresponse()
        except BadStatusLine:
            # XXX: Sometimes, the API server seems to have a problem with
            # keepalives.
            if retry <= 0:
                raise

            self.conn.close()
            self.conn.connect()
            return self._request(method, path, data, headers, retry - 1)

    def _encode_phpargs(self, node, path=None):
        """
        Encode the given 'node' in a way PHP recognizes.

        See https://php.net/manual/function.http-build-query.php for a
        description of the format.

        >>> robot = RobotConnection(None, None)
        >>> enc = lambda arg: sorted(robot._encode_phpargs(arg).items())
        >>> enc({'foo': [1, 2, 3]})
        [('foo[0]', 1), ('foo[1]', 2), ('foo[2]', 3)]
        >>> enc(['a', 'b', 'c'])
        [('0', 'a'), ('1', 'b'), ('2', 'c')]
        >>> enc({'a': {'b': [1, 2, 3], 'c': 'd'}})
        [('a[b][0]', 1), ('a[b][1]', 2), ('a[b][2]', 3), ('a[c]', 'd')]
        >>> enc({})
        []
        >>> enc({'a': {'b': {'c': {}}}})
        []
        >>> enc({'a': [1, 2, 3], 'b': {'c': 4}})
        [('a[0]', 1), ('a[1]', 2), ('a[2]', 3), ('b[c]', 4)]
        """
        if path is None:
            path = []
        if isinstance(node, list):
            enum = enumerate(node)
        elif isinstance(node, dict):
            enum = node.items()
        elif len(path) == 0:
            return node
        else:
            # TODO: Implement escaping of keys.
            flatkey = ("[" + str(x) + "]" for x in path[1:])
            return {str(path[0]) + "".join(flatkey): node}

        encoded = [self._encode_phpargs(v, [*path, k]) for k, v in enum]
        return functools.reduce(lambda a, b: a.update(b) or a, encoded, {})

    def request(self, method, path, data=None, allow_empty=False):
        if data is not None:
            data = urlencode(self._encode_phpargs(data))

        auth = "Basic {}".format(b64encode(f"{self.user}:{self.passwd}".encode("ascii")).decode("ascii"))

        headers = {"Authorization": auth}

        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        self.logger.debug("Sending %s request to Robot at %s with data %r.", method, path, data)

        response = self._request(method, path, data, headers)
        raw_data = response.read().decode("utf-8")
        if len(raw_data) == 0 and not allow_empty:
            msg = "Empty response, status {0}."
            raise RobotError(msg.format(response.status), response.status)
        elif not allow_empty:
            try:
                data = json.loads(raw_data)
            except ValueError as err:
                msg = "Response is not JSON (status {0}): {1}"
                raise RobotError(msg.format(response.status, repr(raw_data))) from err
        else:
            data = None
        self.logger.debug("Got response from Robot with status %d and data %r.", response.status, data)

        if 200 <= response.status < 300:
            return data
        else:
            error = data.get("error", None)
            if error is None:
                raise RobotError(f"Unknown error: {data}", response.status)
            else:
                err = "{} - {}".format(error["status"], error["message"])
                missing = error.get("missing", [])
                invalid = error.get("invalid", [])
                fields = []
                if missing is not None:
                    fields += missing
                if invalid is not None:
                    fields += invalid
                if len(fields) > 0:
                    err += ", fields: {}".format(", ".join(fields))
                raise RobotError(err, response.status)

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, data):
        return self.request("POST", path, data)

    def put(self, path, data):
        return self.request("PUT", path, data)

    def delete(self, path, data=None):
        return self.request("DELETE", path, data, allow_empty=True)


class ServerManager:
    def __init__(self, conn):
        self.conn = conn

    def get(self, ip):
        """
        Get server by providing its main IP address.
        """
        return Server(self.conn, self.conn.get(f"/server/{ip}"))

    def __iter__(self):
        return iter([Server(self.conn, s) for s in self.conn.get("/server")])


class Robot:
    def __init__(self, user, passwd):
        self.conn = RobotConnection(user, passwd)
        self.servers = ServerManager(self.conn)
        self.rdns = ReverseDNSManager(self.conn)
        self.failover = FailoverManager(self.conn, self.servers)
        self.vswitch = VswitchManager(self.conn, self.servers)
