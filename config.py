# <pep8-80 compliant>
"""Configuration values."""

# PROD:
HOST_ = "poly.googleapis.com"

# URL where we should upload files.
UPLOAD_URL = "https://%s/uploads" % HOST_

# URL for the import API endpoint.
IMPORT_URL = "https://%s/v1/assets:startImport" % HOST_

# URL for the poll endpoint. The operation name will be appended.
POLL_URL = "https://%s/v1" % HOST_

