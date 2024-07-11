# <pep8-80 compliant>
"""Imports assets into the Google servers."""

import json
import os
import requests
import time
import webbrowser

from blender2poly import config
from blender2poly import log
from blender2poly.upload import FileUploader

class ImportProcStatus:
    __slots__ = ["uploading", "upload_file", "upload_file_progress"]


class Importer(object):
    """Imports assets into the Google servers.

    This class is responsible for making requests to import assets into the
    Google servers. Given a set of files that make up an asset, this class will
    upload the files to the cloud servers and trigger the import request
    based on those files."""

    # Mapping from file extension to MIME type.
    _MIME_TYPES = {
        ".jpg": "image/jpeg",
        ".mtl": "text/plain",
        ".obj": "text/plain",
        ".png": "image/png",
    }

    # Default MIME type for unrecognized file extensions.
    _DEFAULT_MIME_TYPE = "application/octet-stream"

    STATE_OBJ = 1
    STATE_RESOURCES = 2
    STATE_RESOURCES_UPDATE = 3
    STATE_IMPORT = 4
    STATE_IMPORT_POLL = 5
    STATE_FINISHED = 6


    def __init__(self, access_token):
        """Creates a new Importer with the given access token.

        Args:
            access_token: The OAuth2 bearer token to use when authorizing
                requests to the server.
        """
        self._access_token = access_token
        self.state = Importer.STATE_OBJ
        self.operation = None

    def is_uploading(self):
        return hasattr(self, '_upload_thread') and self._upload_thread.isAlive()

    def start_obj_import(self, obj_file_path, resource_file_paths, callback):
        """Starts importing an asset in OBJ format.

        Args:
            obj_file_path: Local path to the OBJ file.
            resource_file_paths: Array of paths to resource files (textures,
                maps, etc) that are needed by the OBJ file.
            callback: Callback function that gets progress updates. The parameters are
                filename, file_number, total_files, bytes_sent, total_bytes

        Returns:
            The Operation object reported by the server.
        """

        self.resource_file_paths = resource_file_paths
        self.root_file = None
        self.resource_files = []
        self.state = Importer.STATE_OBJ
        self.resource_index = 0
        self.obj_file_path = obj_file_path

        self.uploader = FileUploader(self._access_token)

        # Upload the main file (OBJ file) and record the upload ID.
        self.uploader.begin_upload(obj_file_path, self._get_mime_type(obj_file_path))


        # Now upload each of the resource files.
        self.resource_files = []

    def proc(self):

        return_status = ImportProcStatus()

        if self.state == Importer.STATE_OBJ:
            print("Running OBJ")
            # if we are uploading the obj file, then we wait for it to finish and collect its name
            # and then we move on to upload the resources if there are any otherwise we just import the sucker
            self.root_file, return_status.upload_file_progress = self.uploader.proc_upload()
            return_status.uploading = True
            return_status.upload_file = os.path.basename(self.obj_file_path)
            if not self.root_file is None:
                print("Finished with obj")
                if self.resource_index < len(self.resource_file_paths):
                    self.state = Importer.STATE_RESOURCES
                else:
                    print("Moving to import state")
                    self.state = Importer.STATE_IMPORT
        elif self.state == Importer.STATE_RESOURCES:
            # Begin the upload of the next resource
            path = self.resource_file_paths[self.resource_index]
            return_status.uploading = True
            return_status.upload_file = self.current_file = os.path.basename(path)
            return_status.upload_file_progress = 0
            self.uploader.begin_upload(path, self._get_mime_type(path))
            self.state = Importer.STATE_RESOURCES_UPDATE
        elif self.state == Importer.STATE_RESOURCES_UPDATE:
            resource_file, return_status.upload_file_progress = self.uploader.proc_upload()
            return_status.uploading = True
            return_status.upload_file = self.current_file
            if not resource_file is None:
                print("Got resource " + resource_file)
                self.resource_files.append(resource_file)
                self.resource_index += 1
                if self.resource_index < len(self.resource_file_paths):
                    self.state = Importer.STATE_RESOURCES
                else:
                    print("Finished with resources")
                    self.state = Importer.STATE_IMPORT
        elif self.state == Importer.STATE_IMPORT:
            self.state = Importer.STATE_IMPORT_POLL
            return_status.uploading = False
            # The body of the import request is a JSON object.
            request_body = {
                "importFormat": {
                    "root": self.root_file,
                    "resources": self.resource_files,
                    "formatType": "OBJ"
                }
            }

            headers = self._get_import_headers()

            # Now send it.
            log.debug("Sending import request.")
            log.debug("Request body:\n%s" % json.dumps(request_body, indent="  "))
            response = requests.post(config.IMPORT_URL, headers=headers,
                                     json=request_body)
            log.debug("Import response text: %s" % response.text)
            if response.status_code < 200 or response.status_code > 299:
                # Import failed.
                log.error("Import failed with status %d" % response.status_code)
                raise AssetImportError("Import failed (%d)" % response.status_code)

            self.operation = self._build_operation(response.json())
        elif self.state == Importer.STATE_IMPORT_POLL:
            return_status.uploading = False
            operation = self.operation
            if not operation.done and not operation.error:
                print("Polling operation")
                self.operation = operation = self.poll_operation(operation)
                print("Operation: %s" % operation)
                if operation.error:
                    print("ERROR: %s" % operation.error)
                    self.state = Importer.STATE_FINISHED
                elif operation.result and operation.result.error:
                    print("ERROR: %s" % operation.result.error)
                    self.state = Importer.STATE_FINISHED
                elif operation.done:
                    self.state = Importer.STATE_FINISHED
                    if not operation.result or not operation.result.publishUrl:
                        print('Operation did not return a result/URL.')
                    else:
                        print("Operation is DONE. %s" % operation)
                        url = "https://accounts.google.com/ServiceLogin?passive=1209600&continue={0}?dmr%3D0&followup={0}%3D0".format(operation.result.publishUrl)

                        for browser in ["windows-default", "google-chrome"]:
                            try:
                                webbrowser.get(browser).open(url)
                                break
                            except webbrowser.Error:
                                # Try the next browser in the list.
                                continue
                        else:
                            webbrowser.open(url)

        return return_status

    def setup_callback(filename, file_number, total_files, user_callback):

        def cbk(bytes_sent, total_bytes):
            user_callback(filename, file_number, total_files, bytes_sent, total_bytes)
            pass

        return cbk


    def poll_operation(self, operation):
        """Polls the server for an update on the given operation.
        
        Args:
            operation: the Operation to poll for.

        Returns:
            A new Operation object with the current state of the operation.
        """
        if not operation.name.startswith("operations/"):
            raise ValueError("Operation name must start with 'operations/'")
        url = "%s/%s" % (config.POLL_URL, operation.name)
        log.debug("Polling operation: %s, url %s" % (operation, url))
        response = requests.get(url, headers=self._get_import_headers())
        log.debug("Operation poll response: %s" % response.text)
        if response.status_code < 200 or response.status_code > 299:
            # Failed.
            log.error("Operation poll failed, status %d" % response.status_code)
            raise AssetImportError("Poll failed (%d)" % response.status_code)
        return self._build_operation(response.json())


    def _build_operation(self, data):
        """Builds an Operation object from its JSON dictionary representation.

        Args:
            data: the JSON dictionary representation of the Operation.

        Returns:
            The Operation object.

        Raises:
            AssetImportError: if there is an error parsing the response.
        """
        try:
            return Operation(data)
        except Exception as ex:
            log.error("Failed to parse response as an Operation object.")
            raise AssetImportError("Failed to parse response as Operation", ex)

    def _get_import_headers(self):
        """Returns a dict of HTTP headers to send with the import request."""
        return {
            "Authorization": "Bearer " + self._access_token,
            #"X-Google-Project-Override": "apikey",
            "Content-Type": "application/json",
            "X-GFE-SSL": "yes"
        }

    def _get_mime_type(self, file_name):
        """Returns the MIME type for the given file name."""
        _, file_name = os.path.splitext(file_name.lower())
        if file_name in self._MIME_TYPES:
            return self._MIME_TYPES[file_name]
        else:
            return self._DEFAULT_MIME_TYPE


class AssetImportError(Exception):
    """Represents an error while importing an asset."""
    def __init__(self, msg, cause=None):
        super(AssetImportError, self).__init__(msg, cause)


class Operation(object):
    """Represents an ongoing import operation performed by the server."""
    def __init__(self, data):
        """Constructs an Operation from its JSON dictionary representation.
        
        Args:
            data: The JSON dictionary with the representation of the Operation.
        """
        if "name" not in data:
            raise ValueError("Operation object must have a name.")
        self.name = data["name"]
        self.done = ("done" in data and data["done"])
        self.error = None
        self.result = None

        if "error" in data:
            if "message" in data["error"]:
                self.error = "Error: " + data["error"]["message"]
            else:
                self.error = "An error occurred."
        if "response" in data:
            self.result = AssetImportResult(data["response"])

    def __str__(self):
        return ("Operation(name=%s, done=%s, error=%s, result=%s)" % (self.name, self.done, self.error, self.result))


class AssetImportResult(object):
    """Represents an asset import result.
    
    Corresponds to the StartAssetImportResponse message from the server.

    Fields:
        assetId: The ID of the imported asset
        publishUrl: The URL of the publish page for this asset.
        messages: Array of strings representing the import messages, if any.
    """
    def __init__(self, data):
        """Constructs from the JSON dictionary representation.

        Args:
            data: The JSON dictionary representation."""
        self.assetId = data["assetId"] if "assetId" in data else None
        self.publishUrl = data["publishUrl"] if "publishUrl" in data else None
        self.messages = []
        self.error = None
        if "assetImportMessages" in data:
            print("Extracting the assetImportMessages")
            importMessages = data["assetImportMessages"]
            for item in importMessages:
                print("Found item: %s" % repr(item))
                if "code" in item and item["code"] == "FATAL_ERROR":
                    print("Found a fatal error")
                    self.error = repr(item)
                # Since these messages are only for logging, we don't care
                # about the presentation, so just use the raw representation.
                self.messages.append(repr(item))

