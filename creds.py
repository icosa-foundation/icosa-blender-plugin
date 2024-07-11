# <pep8-80 compliant>
"""API credentials.

Attributes:
    API_KEY: the API key for the project.
    CLIENT_ID: the client ID to use for the API requests.
    CLIENT_SECRET: the client secret to use for the API requests.
"""

# TODO: enter your credentials here
API_KEY="AIzaSyAedyQXqilfH797ZqQoAYq00FSx85z59FQ"
CLIENT_ID="48072656761-cg058q0287q2rof3e2glfg5sgk8qrl1b.apps.googleusercontent.com"
CLIENT_SECRET="1zQMqI0VbmqoZLKC1e0YAy7L"

if len(API_KEY) == 0 or len(CLIENT_ID) == 0 or len(CLIENT_SECRET) == 0:
    raise Exception("Please enter your credentials in creds.py")

