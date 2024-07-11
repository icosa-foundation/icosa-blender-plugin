# <pep8-80 compliant>
"""Handles signing into Google to use the Poly API."""

import os
import re
import requests
import socket
import select
import webbrowser
import urllib

from blender2poly import creds
from blender2poly import log


class PolySignIn(object):
    """Handles signing into Poly.

    Attributes:
        access_token: The access token (available after auth is complete).
        refresh_token: The refresh token (available after auth is complete).
    """
    # Range of ports to try when listening to the authentication response.
    _PORT_RANGE=range(12345,12400)
    # Redirect URI to use in authentication (format string).
    _REDIRECT_URI_FORMAT = "http://localhost:%d/callback"
    # TODO: STOPSHIP: find out what scopes we actually need to authorize.
    _SCOPES=("https://www.googleapis.com/auth/vrassetdata.readwrite "
             "https://www.googleapis.com/auth/vrassetdata.readonly")
    _BROWSERS_TO_TRY = ["windows-default", "google-chrome"]
    _SUCCESS_RESPONSE = ("Authentication success. You can close this "
                         "window/tab and return to the application.")
    _ERROR_RESPONSE = "Authentication failure. Try again in a few minutes."
    _TOKEN_DIR = os.path.expanduser("~") + "/blender2poly"
    _TOKEN_FILENAME = _TOKEN_DIR + "/tok"


    def __init__(self):
        """Creates a new PolySignIn object."""
        self.access_token = None
        self.refresh_token = None

        # attempt to read the access token
        try:
            if os.path.exists(self._TOKEN_FILENAME):
                access_token_file = open(self._TOKEN_FILENAME, "r")
                if access_token_file.mode == 'r':
                    self.access_token, self.refresh_token = access_token_file.readlines()
                    log.debug("Found token: " + self.access_token)
                    log.debug("Found refresh token: " + self.refresh_token)
        except:
            self.access_token = None
            self.refresh_token = None
            log.debug("Couldn't get the access token from file")


    def authenticate(self, force_login):
        """Launches the browser-based authentication flow.

        If this method succeeds, the access token will be available in the
        access_token attribute, and the refresh token in the refresh_token
        attribute.

        Throws:
            SignInError: if the sign-in process failed.
        """

        try:
            # Allocate port and prepare server socket.
            self.server, self.port = self._prepare_server_socket()

            if self.refresh_token is None or force_login:
                # Launch the user's browser for the sign in process.
                self._launch_browser_sign_in(self.port)
                self.waiting_for_signin = True
            else:
                self._exchange_auth_code_for_tokens(self.refresh_token, self.port, True)
                self.waiting_for_signin = False
        except:
            if self.server is not None: self.server.close()
            raise

    def process_auth(self):
        """ Checks if the auth code is available and process it
        Returns: True if there was an auth code or if there was an error
            False if the auth code is not available yet
        """

        print("Waiting for signing: {0}".format(self.waiting_for_signin))
        if not self.waiting_for_signin:
            print("Not waiting for a sign in")
            return True

        try:
            # Listen for the auth code on the local socket.
            auth_code = self._listen_for_auth_code(self.server)

            log.debug("Waiting for auth code")

            # if we have received the authcode, then process it
            if auth_code is not None:
                # Now that we have the auth code, exchange for tokens.
                self._exchange_auth_code_for_tokens(auth_code, self.port, False)
                
                if not os.path.exists(self._TOKEN_DIR):
                    os.makedirs(self._TOKEN_DIR)
                #store the access token and refresh token for future use
                access_token_file = open(self._TOKEN_FILENAME, "w+")
                access_token_file.writelines([self.access_token, "\n", self.refresh_token])
                access_token_file.close()
                # And we're done.
                log.debug("Authentication successful.")
                self.waiting_for_signin = False
                return True
        except AssertionError as error:
            print(error)
            self.finish_auth()
            self.waiting_for_signin = False
            return True
        return False

    def finish_auth(self):
        if self.server is not None: self.server.close()

    def _launch_browser_sign_in(self, port):
        """Launches a browser to start the sign in process.
        
        Args:
            port: the port number to use.

        Throws:
            SignInError: if there is a problem launching the browser.
        """
        url = ("https://accounts.google.com/o/oauth2/auth?%s" %
            urllib.parse.urlencode({
                "client_id": creds.CLIENT_ID,
                "redirect_uri" : (self._REDIRECT_URI_FORMAT % port),
                "response_type": "code",
                "scope": self._SCOPES}))
        log.debug("Launching browser for URL %s" % url)
        for browser in self._BROWSERS_TO_TRY:
            try:
                webbrowser.get(browser).open(url)
                break
            except webbrowser.Error:
                # Try the next browser in the list.
                continue
        else:
            webbrowser.open(url)


    def _prepare_server_socket(self):
        """Prepares the server socket to listen for the authentication code.

        This only allocates a port and sets up the socket, but doesn't put
        the socket into listen mode yet. For that, see _listen_for_auth_code().

        Returns:
            (socket, port): The server socket and port on which it is set up.
        """
        server = None
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Try the ports in our range until we can bind.
            for port in self._PORT_RANGE:
                # Try to bind to this port.
                try:
                    server.bind(('',port))
                    # If we got here without throwing, we were successful.
                    log.debug("Server socket will use port %d" % port)
                    return server, port
                except OSError:
                    # Can't bind to this port. Try the next one.
                    log.debug("Couldn't use port %d" % port)
                    pass

            # If we got here, we tried all the ports and failed.
            raise SignInError("No port available for local socket.")
        except:
            if server is not None: server.close()
            raise


    def _listen_for_auth_code(self, server):
        """Opens a local server socket to listen for the auth code.

        This will open a local server on port self._PORT to listen for the
        authentication code as part of the sign-in process. This method
        will block until the access code is read.

        Args:
            server: the server socket to use to listen for the auth code.
        
        Throws:
            IOError: if there is an error listening to or reading the auth
                code from the local server socket.
        """
        client = None
        try:
            server.listen(0)  # 0 backlog (only one connection needed)
            read_list = [server]
            readable, writable, errored = select.select(read_list, [], [], 0)
            if server in readable:
                client, client_addr = server.accept()
                req = client.recv(1024).decode("utf-8")
                m = re.search('[?]code=(.*)[& ]', req)
                if not m:
                    # The request came, but we couldn't parse the access code.
                    # Shouldn't happen.
                    log.error("Didn't get auth code in request: %s" % req)
                    self._send_plain_response(client, 500, "Internal Server Error",
                                              self._ERROR_RESPONSE)
                    raise SignInError("Auth code missing in request.")
                code = m.group(1)
                log.debug("Got auth code %s" % code)
                self._send_plain_response(client, 200, "OK", self._SUCCESS_RESPONSE)
                return code
        finally:
            # Ensure client socket is closed so it doesn't leak.
            if client is not None:
                log.debug("Closing client socket")
                client.close()
        return None


    def _exchange_auth_code_for_tokens(self, code, port, refresh):
        """Exchanges the given authorization code for access/refresh tokens.

        Args:
            code: the authentication code to exchange.
            port: the port to use in the redirect URI.

        Returns:
            A tuple of (access_token, refresh_token) with the access and refresh
            tokens given by the server in exchange for the auth code.
        """
        log.debug("Exchanging auth code for token.")
        resp = requests.post("https://accounts.google.com/o/oauth2/token", {
            "refresh_token" if refresh else "code": code,
            "client_id": creds.CLIENT_ID,
            "client_secret": creds.CLIENT_SECRET,
            "redirect_uri" : (self._REDIRECT_URI_FORMAT % port),
            "grant_type": "refresh_token" if refresh else "authorization_code"
        })
        if not resp:
            log.error("Error getting auth token. Response: %s" % resp.text)
            raise SignInError("Error getting auth token from auth code.")
        m = re.search('"access_token" *: *"(.*)"', resp.text)
        if not m:
            log.error("Access token not found in response: %s" % resp.text)
            raise SignInError("Access token not found in auth response.")
        access_token = m.group(1)
        log.debug("Access token: %s" % access_token)
        self.access_token = access_token

        if not refresh:
            m = re.search('"refresh_token" +: +"(.*)"', resp.text)
            if not m:
                log.error("*** Refresh token not found in response: %s" % resp.text)
                raise SignInError("Refresh token not found in auth response.")
            refresh_token = m.group(1)
            log.debug("Refresh token: %s" % refresh_token)
            self.refresh_token = refresh_token


    def _send_plain_response(self, client, status_code, reason_phrase, response):
        """Sends a text response to the given client.

        Args:
            client: A client socket to which to write the response.
            status_code: The HTTP status code to include in the response.
            reason_phrase: The reason phrase to use in the response.
            response: A string with the response text to write.
        """
        response_bytes = str.encode(response, "utf-8")
        response_length = len(response_bytes)
        header_format = (
            "HTTP/1.1 %d %s\n"
            "Content-Type: text/plain\n"
            "Content-Length: %d\n\n")
        header_bytes = str.encode(
            header_format % (status_code, reason_phrase, response_length))
        client.send(header_bytes + response_bytes)


class SignInError(Exception):
    """Represents an error while signing in."""
    def __init__(self, msg, cause=None):
        super(SignInError, self).__init__(msg, cause)

