# <pep8-80 compliant>
"""Handles uploading of files to Google cloud servers."""

import os
import requests
import http
import json

from blender2poly import config


class FileUploader(object):
    """Uploads files to Google cloud servers.
    
    The process of starting the importation of a 3D asset in Poly requires the
    caller to upload each individual file that makes up the asset. For example,
    for an OBJ import, this would be the OBJ file, the MTL file and any texture
    files.
    
    This class handles the uploading of these individual files.
    
    Each uploaded file receives an "upload ID", which should then be used as
    part of the asset import request.
    """

    def __init__(self, access_token):
        """Initializes the file uploader with the given authentication token.

        Args:
            access_token: The OAuth2 bearer token to use when uploading files.
        """
        if type(access_token) is not str or len(access_token) < 1:
            raise ValueError("A non-empty access_token is required.")
        self._access_token = access_token


    def begin_upload(self, file_path, mime_type):
        """Uploads a file to the servers.

        Args:
            file_path: Local path to the file to upload. This can be absolute
                or relative to the current directory.  mime_type: The MIME type
                to use for the file. For example, for a PNG file this would be
                "image/png".

        Returns:
            The upload ID returned by the server (string).

        Raises:
            IOError: An error occurred while reading the source file from disk.
            UploadError: An error occurred while uploading the file to the
                server.
        """
        self.file = open(file_path, "rb")
        # Basename is just the file name part of the path. For example, if
        # file_path is "/foo/bar/qux.obj", then basename will be "qux.obj".
        basename = os.path.basename(file_path)

        self.file_size = os.stat(file_path).st_size
        self.current_bytes = 0

        print("File Size: %d" % self.file_size)

        boundary = "d5863be2b7234d17a3348556e8b757b5"
        formhead = bytes("--{0}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{1}\"\r\nContent-Type: {2}\r\n\r\n".format(boundary, basename, mime_type), "utf-8")
        self.formfoot = bytes("\r\n--{0}--\r\n".format(boundary), "utf-8")
        http.client.HTTPConnection.debuglevel=1
        self.connection = http.client.HTTPSConnection(config.HOST_)
        self.connection.connect()
        self.connection.putrequest('POST', "/uploads")
        self.connection.putheader("Connection", "Keep-Alive")
        self.connection.putheader("Content-Length", self.file_size + len(formhead) + len(self.formfoot))
        self.connection.putheader('Authorization', "Bearer " + self._access_token)
        self.connection.putheader("Content-Type", "multipart/form-data;boundary=" + boundary)
        self.connection.endheaders()
        self.connection.send(formhead)

    def proc_upload(self):
        file_bytes = self.file.read(512000)
        num_bytes = len(file_bytes)
        self.current_bytes += num_bytes
        if file_bytes:
            print("Sending {0} bytes".format(num_bytes))
            self.connection.send(file_bytes)
        else:
            self.file.close()
            self.connection.send(self.formfoot)
            response = self.connection.getresponse()
            if response.status >= 200 and response.status <= 299:
                # Uploaded succeeded.
                d = json.loads(response.read().decode("utf-8"))
                uploadId = d['elementId']
                if not uploadId:
                    # Shouldn't happen[tm].
                    raise UploadError("Upload failed: no upload ID received.")
                return (uploadId, 1.0)
            else:
                # Upload failed.
                message = "Upload failed: got status {0} - {1}".format(response.status, response.reason)

            raise UploadError(message)

        return (None, float(self.current_bytes) / float(self.file_size))

    def create_progress_callback(encoder, user_callback):

        encoder_len = encoder.len
        def progress(monitor):
            #print("{0}/{1}".format(monitor.bytes_read, encoder_len))
            user_callback(monitor.bytes_read, encoder_len)

        return progress


class UploadError(Exception):
    """Represents an error during a file upload process."""
    def __init__(self, msg, cause=None):
        super(UploadError, self).__init__(msg, cause)

