"""
Copyright 2021 Sketchfab
Copyright 2025 Icosa Foundation

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

This file has been modified from its original version.
"""
from collections import OrderedDict
import functools
import glob
import json
import os
import shutil
import subprocess
import tempfile
import threading
import urllib
import urllib.parse
from uuid import UUID

import requests

import bpy
import bpy.utils.previews
from bpy.props import (StringProperty,
                       EnumProperty,
                       BoolProperty,
                       IntProperty,
                       PointerProperty)

bl_info = {
    'name': 'Icosa Gallery Addon',
    'description': 'Browse, download from and publish to the Icosa 3D models Gallery',
    'author': 'Icosa Foundation',
    'license': 'SPDX:GPL-3.0-or-later',
    'deps': '',
    'version': (0, 0, 1),
    "blender": (4, 2, 0),
    'location': 'View3D > Tools > Icosa Gallery',
    'warning': '',
    'wiki_url': 'https://github.com/icosa-foundation/icosa-blender-plugin/releases',
    'tracker_url': 'https://github.com/icosa-foundation/icosa-blender-plugin/issues',
    'link': 'https://github.com/icosa-foundation/icosa-blender-plugin',
    'support': 'COMMUNITY',
    'category': 'Import-Export'
}
bl_info['blender'] = getattr(bpy.app, "version")


PLUGIN_VERSION = str(bl_info['version']).strip('() ').replace(',', '.')
preview_collection = {}
thumbnailsProgress = set([])
ongoingSearches = set([])
is_plugin_enabled = False


class Config:

    ADDON_NAME = 'io_icosa_gallery'
    GITHUB_REPOSITORY_URL = 'https://github.com/icosa-foundation/blender-plugin'
    GITHUB_REPOSITORY_API_URL = 'https://api.github.com/repos/icosa-foundation/blender-plugin'
    # CLIENTID = ''
    ICOSA_URL = 'https://icosa.gallery'
    ICOSA_GET_DEVICE_CODE = f'{ICOSA_URL}/device'
    ICOSA_EMAIL_AUTH = f'{ICOSA_URL}/login'  # Not currently used
    ICOSA_SIGNUP = f'{ICOSA_URL}/register'
    ICOSA_REPORT_URL = f'{ICOSA_URL}/contact'

    ICOSA_API = 'https://api.icosa.gallery/v1'

    ICOSA_MODEL = f'{ICOSA_API}/assets'
    ICOSA_UPLOAD = f'{ICOSA_API}/assets'
    ICOSA_DEVICE_AUTH = f'{ICOSA_API}/login/device_login'

    ICOSA_ME = f'{ICOSA_API}/users/me'

    # Always filter by remixable except for your own models
    BASE_SEARCH_OWN_MODELS = f'{ICOSA_ME}/assets?'
    BASE_SEARCH_LIKED_MODELS = f'{ICOSA_ME}/likedassets?license=REMIXABLE&'
    BASE_SEARCH = f'{ICOSA_API}/assets?license=REMIXABLE'
    DEFAULT_SEARCH = f'{BASE_SEARCH}&orderBy=BEST&format=-TILT' # TODO remove the need for this

    ICOSA_PLUGIN_VERSION = '{}/releases'.format(GITHUB_REPOSITORY_API_URL)

    # Those will be set during plugin initialization, or upon setting a new cache directory
    ICOSA_TEMP_DIR = ""
    ICOSA_THUMB_DIR = ""
    ICOSA_MODEL_DIR = ""

    ICOSA_CATEGORIES = (
        ('ALL', 'All categories', 'All categories'),
        ('ANIMALS', 'Animals & Pets', 'Animals & Pets'),
        ('ARCHITECTURE', 'Architecture', 'Architecture'),
        ('ART', 'Art', 'Art'),
        ('CULTURE', 'Culture & Humanity', 'Culture & Humanity'),
        ('EVENTS', 'Current Events', 'Current Events'),
        ('FOOD', 'Food & Drink', 'Food & Drink'),
        ('HISTORY', 'History', 'History'),
        ('HOME', 'Furniture & Home', 'Furniture & Home'),
        ('MISCELLANEOUS', 'Miscellaneous', 'Miscellaneous'),
        ('NATURE', 'Nature', 'Nature'),
        ('OBJECTS', 'Objects', 'Objects'),
        ('PEOPLE', 'People & Characters', 'People & Characters'),
        ('PLACES', 'Places & Scenes', 'Places & Scenes'),
        ('SCIENCE', 'Science', 'Science'),
        ('SPORTS', 'Sports & Fitness', 'Sports & Fitness'),
        ('TECH', 'Tools & Technology', 'Tools & Technology'),
        ('TRANSPORT', 'Transport', 'Transport'),
        ('TRAVEL', 'Travel & Leisure', 'Travel & Leisure')
    )

    ICOSA_FACECOUNT = (
        ('ANY', "All", ""),
        ('10K', "Up to 10k", ""),
        ('50K', "10k to 50k", ""),
        ('100K', "50k to 100k", ""),
        ('250K', "100k to 250k", ""),
        ('250KP', "250k +", "")
    )

    ICOSA_SORT_BY = (
        ('BEST', "Best", ""),
        ('NEWEST', "Newest", ""),
        ('OLDEST', "Oldest", ""),
        ('TRIANGLE_COUNT', "Triangle Count", ""),
        ('LIKED_TIME', "Recently Liked", ""),
        ('UPDATE_TIME', "Recently Updated", ""),
        ('LIKES', "Most Likes", ""),
        ('DOWNLOADS', "Most Downloads", ""),
        ('DISPLAY_NAME', "Title", ""),
        ('AUTHOR_NAME', "Author", "")
    )

    ICOSA_SEARCH_DOMAIN = (
        ('DEFAULT', "Whole site", "", 0),
        ('OWN', "Your Models", "", 1),
        ('LIKED', "Your Likes", "", 2)
    )

    MAX_THUMBNAIL_HEIGHT = 256

    ICOSA_UPLOAD_LIMITS = {
        "basic": 100 * 1024 * 1024,
    }

class Utils:
    def humanify_size(size):
        suffix = 'B'
        readable = size

        # Megabyte
        if size > 1048576:
            suffix = 'MB'
            readable = size / 1048576.0
        # Kilobyte
        elif size > 1024:
            suffix = 'KB'
            readable = size / 1024.0

        readable = round(readable, 2)
        return '{}{}'.format(readable, suffix)

    def humanify_number(number):
        suffix = ''
        readable = number

        if number > 1000000:
            suffix = 'M'
            readable = number / 1000000.0

        elif number > 1000:
            suffix = 'K'
            readable = number / 1000.0

        readable = round(readable, 2)
        return '{}{}'.format(readable, suffix)

    def thumbnail_file_exists(asset_id):
        return os.path.exists(os.path.join(Config.ICOSA_THUMB_DIR, '{}.png'.format(asset_id)))

    @staticmethod
    def clean_thumbnail_directory():
        if not os.path.exists(Config.ICOSA_THUMB_DIR):
            return

        from os import listdir
        for file in listdir(Config.ICOSA_THUMB_DIR):
            os.remove(os.path.join(Config.ICOSA_THUMB_DIR, file))

    def clean_downloaded_model_dir(asset_id):
        shutil.rmtree(os.path.join(Config.ICOSA_MODEL_DIR, asset_id))

    def get_thumbnail_url(thumbnails_json):
        best_thumbnail = thumbnails_json['url']
        return best_thumbnail

    @staticmethod
    def setup_plugin():
        if not os.path.exists(Config.ICOSA_THUMB_DIR):
            os.makedirs(Config.ICOSA_THUMB_DIR)

    def get_asset_id_from_model_url(model_url):
        try:
            return model_url.split('/')[5]
        except:
            ShowMessage("ERROR", "Url parsing error", "Error getting assetId from url: {}".format(model_url))
            return None

    def clean_node_hierarchy(objects, root_name):
        """
        Removes the useless nodes in a hierarchy
        TODO: Keep the transform (might impact Yup/Zup)
        """
        # Find the parent object
        root = None
        for object in objects:
            if object.parent is None:
                root = object
        if root is None:
            return None

        # Go down its hierarchy until one child has multiple children, or a single mesh
        # Keep the name while deleting objects in the hierarchy
        diverges = False
        while diverges==False:
            children = root.children
            if children is not None:

                if len(children)>1:
                    diverges = True
                    root.name = root_name

                if len(children)==1:
                    if children[0].type != "EMPTY":
                        diverges = True
                        root.name = root_name
                        if children[0].type == "MESH": # should always be the case
                            matrixcopy = children[0].matrix_world.copy()
                            children[0].parent = None
                            children[0].matrix_world = matrixcopy
                            bpy.data.objects.remove(root)
                            children[0].name = root_name
                            root = children[0]

                    elif children[0].type == "EMPTY":
                        diverges = False
                        matrixcopy = children[0].matrix_world.copy()
                        children[0].parent = None
                        children[0].matrix_world = matrixcopy
                        bpy.data.objects.remove(root)
                        root = children[0]
            else:
                break

        # Select the root Empty node
        root.select_set(True)

    def is_valid_uid(uid_to_test, version=4):
        try:
            uid_obj = UUID(hex=uid_to_test, version=version)
            return True
        except ValueError:
            return False

class Cache:
    ICOSA_CACHE_FILE = os.path.join(
        bpy.utils.user_resource("SCRIPTS", path="icosa_cache", create=True),
        ".cache"
    )  # Use a user path to avoid permission-related errors

    @staticmethod
    def read():
        if not os.path.exists(Cache.ICOSA_CACHE_FILE):
            return {}

        with open(Cache.ICOSA_CACHE_FILE, 'rb') as f:
            data = f.read().decode('utf-8')
            return json.loads(data)

    def get_key(key):
        cache_data = Cache.read()
        if key in cache_data:
            return cache_data[key]

    def save_key(key, value):
        cache_data = Cache.read()
        cache_data[key] = value
        with open(Cache.ICOSA_CACHE_FILE, 'wb+') as f:
            f.write(json.dumps(cache_data).encode('utf-8'))

    def delete_key(key):
        cache_data = Cache.read()
        if key in cache_data:
            del cache_data[key]

        with open(Cache.ICOSA_CACHE_FILE, 'wb+') as f:
            f.write(json.dumps(cache_data).encode('utf-8'))


# helpers
def get_icosa_login_props():
    return bpy.context.window_manager.icosa_api


def get_icosa_props():
    return bpy.context.window_manager.icosa_browser


def get_icosa_props_proxy():
    return bpy.context.window_manager.icosa_browser_proxy


def get_icosa_model(asset_id):
    icosa_props = get_icosa_props()
    if "current" in icosa_props.search_results and asset_id in icosa_props.search_results["current"]:
        return icosa_props.search_results['current'][asset_id]
    else:
        return None


def run_default_search():
    searchthr = GetRequestThread(Config.DEFAULT_SEARCH, parse_results)
    searchthr.start()


def get_plugin_enabled():
    global is_plugin_enabled
    return is_plugin_enabled


def refresh_search(self, context):
    pprops = get_icosa_props_proxy()
    if pprops.is_refreshing:
        return

    props = get_icosa_props()

    if pprops.search_domain != props.search_domain:
        props.search_domain = pprops.search_domain
        # get_sorting_options(context)
    if pprops.sort_by != props.sort_by:
        props.sort_by = pprops.sort_by

    if 'current' in props.search_results:
        del props.search_results['current']

    props.query = pprops.query
    props.curated = pprops.curated
    props.include_tiltbrush = pprops.include_tiltbrush
    props.categories = pprops.categories
    props.face_count = pprops.face_count
    bpy.ops.wm.icosa_search('EXEC_DEFAULT')


def set_login_status(status_type, status):
    login_props = get_icosa_login_props()
    login_props.status = f"{status}"
    login_props.status_type = status_type


def set_import_status(status):
    props = get_icosa_props()
    props.import_status = status


# Simple wrapper around requests.get for debugging purposes
def requests_get(*args, **kwargs):
    return requests.get(*args, **kwargs)


class IcosaApi:

    def __init__(self):
        self.access_token = ''
        self.api_token = ''
        self.headers = {}
        self.username = ''
        self.display_name = ''
        self.next_results_url = None
        self.prev_results_url = None

    def build_headers(self):
        if self.access_token:
            self.headers = {'Authorization': 'Bearer ' + self.access_token}
        elif self.api_token:
            self.headers = {'Authorization': 'Token ' + self.api_token}
        else:
            print("Empty authorization header")
            self.headers = {}

    def login(self, email, password, api_token):
        bpy.ops.wm.login_modal('INVOKE_DEFAULT')

    def is_user_logged(self):
        if (self.access_token or self.api_token) and self.headers:
            return True

        return False

    def logout(self):
        self.access_token = ''
        self.api_token = ''
        self.headers = {}
        Cache.delete_key('username')
        Cache.delete_key('access_token')
        Cache.delete_key('api_token')
        Cache.delete_key('key')

        props = get_icosa_props()
        #props.search_domain = "DEFAULT"
        if 'current' in props.search_results:
            del props.search_results['current']
        pprops = get_icosa_props_proxy()
        #pprops.search_domain = "DEFAULT"

        bpy.ops.wm.icosa_search('EXEC_DEFAULT')

    def request_user_info(self):
        requests_get(Config.ICOSA_ME, headers=self.headers, hooks={'response': self.parse_user_info})

    def get_user_info(self):
        if self.display_name:
            return '{}'.format(self.display_name)
        else:
            return ('', '')

    def parse_user_info(self, r, *args, **kargs):
        if r.status_code == 200:
            user_data = r.json()
            self.username = user_data['email']
            self.display_name = user_data['displayName']
        else:
            set_login_status('ERROR', 'Not logged in')
            ShowMessage("ERROR", "Failed to authenticate", f"{r.status_code} - {r.text}")
            self.access_token = ''
            self.api_token = ''
            self.headers = {}

    def request_thumbnail(self, thumbnails_json, asset_id):
        # Avoid requesting twice the same data
        if asset_id not in thumbnailsProgress:
            thumbnailsProgress.add(asset_id)
            url = Utils.get_thumbnail_url(thumbnails_json)
            thread = ThumbnailCollector(url, asset_id)
            thread.start()

    def request_model_info(self, asset_id, callback=None):
        if callback is None:
            callback = self.handle_model_info
        callback = functools.partial(callback, asset_id)
        url = f"{Config.ICOSA_MODEL}/{asset_id}"
        model_infothr = GetRequestThread(url, callback, self.headers)
        model_infothr.start()

    def handle_model_info(self, r, asset_id, *args, **kwargs):
        icosa_props = get_icosa_props()

        # Dirty fix to avoid processing obsolete result data
        if 'current' not in icosa_props.search_results or asset_id is None or asset_id not in icosa_props.search_results['current']:
            return

        model = icosa_props.search_results['current'][asset_id]
        json_data = r.json()
        model.license = json_data.get('license', {})
        icosa_props.search_results['current'][asset_id] = model

    def search(self, query, search_cb):
        icosa_props = get_icosa_props()

        if icosa_props.search_domain == "OWN":
            url = Config.BASE_SEARCH_OWN_MODELS
        elif icosa_props.search_domain == "LIKED":
            url = Config.BASE_SEARCH_LIKED_MODELS
        else:
            url = Config.BASE_SEARCH

        search_query = '{}{}'.format(url, query)
        if search_query not in ongoingSearches:
            ongoingSearches.add(search_query)
            searchthr = GetRequestThread(search_query, search_cb, self.headers)
            searchthr.start()

    def search_cursor(self, url, search_cb):
        requests_get(url, headers=self.headers, hooks={'response': search_cb})

    def write_model_info(self, title, author, author_url, _license, asset_id):
        try:
            downloadHistory = bpy.context.preferences.addons[__name__.split('.')[0]].preferences.downloadHistory
            if downloadHistory != "":
                downloadHistory = os.path.abspath(downloadHistory)
                createFile = False
                if not os.path.exists(downloadHistory):
                    createFile = True
                with open(downloadHistory, 'a+') as f:
                    if createFile:
                        f.write("Model name, Author name, Author url, License, Model link,\n")
                    f.write("{}, {}, https://icosa.gallery/{}, {}, https://icosa.gallery/view/{},\n".format(
                        title.replace(",", " "),
                        author.replace(",", " "),
                        author_url.replace(",", " "),
                        _license.replace(",", " "),
                        asset_id
                    ))
        except:
            print("Error encountered while saving data to history file")

    def parse_model_info_request(self, r, *args, **kargs):
        try:
            if r.status_code == 200:
                result = r.json()
                _title = result['displayName']
                _author = result['authorName']
                _username = result['authorId']
                _license = result["license"]
                _asset_id = result['assetId']
                self.write_model_info(_title, _author, _username, _license, _asset_id)
            else:
                print("Error encountered while getting model info ({})\n{}\n{}".format(r.status_code, r.url, str(r.json())))
        except:
            print("Error encountered while parsing model info request: {}".format(r.url))

    def download_model(self, asset_id):
        icosa_model = get_icosa_model(asset_id)
        if icosa_model is not None:  # The model comes from the search results
            if icosa_model.zip_archive_url:  # TODO handle expiration: and (time.time() - icosa_model.time_url_requested < icosa_model.url_expires):
                self.get_download(icosa_model.zip_archive_url, [], asset_id, icosa_model.title)
            elif icosa_model.download_url:
                self.get_download(icosa_model.download_url, icosa_model.resource_urls, asset_id, icosa_model.title)
        else:  # Model comes from a direct link
            icosa_props = get_icosa_props()
            # TODO

    def get_download(self, main_url, additional_urls, asset_id, title):

        print(f"main_url: {main_url}")

        main_filename = urllib.parse.urlparse(main_url).path.split('/')[-1]
        # If the main url is a zip file, we never need to download additional files
        if main_filename.endswith('.zip'):
            additional_urls = []

        if main_url is None:
            print('Url is None')
            return

        temp_dir = os.path.join(Config.ICOSA_MODEL_DIR, asset_id)
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)

        all_urls = [main_url] + additional_urls

        main_resource_path = None

        print(f"all_urls: {all_urls}")
        for url in all_urls:
            resource_filename = urllib.parse.urlparse(url).path.split('/')[-1]

            resource_path = os.path.join(temp_dir, resource_filename)
            if not main_resource_path:
                main_resource_path = resource_path

            if not os.path.exists(resource_path):  # Not downloaded yet

                # wm = bpy.context.window_manager
                # wm.progress_begin(0, 100)
                # set_log("Downloading model..")

                with open(resource_path, "wb") as f:
                    req = requests_get(url, stream=True)
                    f.write(req.content)

                # TODO: Handle progress
                #     total_length = req.headers.get('content-length')
                #     if total_length is None:  # no content length header
                #         f.write(req.content)
                #     else:
                #         dl = 0
                #         total_length = int(total_length)
                #         for data in req.iter_content(chunk_size=4096):
                #             dl += len(data)
                #             f.write(data)
                #             done = int(100 * dl / total_length)
                #             wm.progress_update(done)
                #             set_log("Downloading model..{}%".format(done))
                # wm.progress_end()

            else:

                print('Model already downloaded')

        gltf_path = None
        if main_filename.endswith('.zip'):
            extract_path = unzip_archive(resource_path)
            # Get the first gltf file in the extracted directory
            # TODO Handle scenario where there are zero or multiple gltf files
            gltf_files = glob.glob(os.path.join(extract_path, '*.gltf'))
            if gltf_files:
                gltf_path = gltf_files[0]
        else:
            gltf_path = main_resource_path
        print(f"gltf_path: {gltf_path}")
        print(f"main_resource_path: {main_resource_path}")

        if gltf_path:
            try:
                import_model(gltf_path, asset_id, title)
            except Exception as e:
                import traceback
                print(traceback.format_exc())
        else:
            ShowMessage("ERROR", "Download error", "Failed to download model (url might be invalid)")
            model = get_icosa_model(asset_id)
            set_import_status("Import model ({})".format(model.download_size if model.download_size else 'fetching data'))
        return


class IcosaLoginProps(bpy.types.PropertyGroup):
    def update_tr(self, context):
        self.status = ''
        if self.email != self.last_username or self.password != self.last_password:
            self.last_username = self.email
            self.last_password = self.password
            if not self.password:
                set_login_status('ERROR', 'Password is empty')
            bpy.ops.wm.icosa_login('EXEC_DEFAULT')


    email: StringProperty(
        name="email",
        description="User email",
        default=""
    )

    api_token: StringProperty(
        name="API Token",
        description="User API Token",
        default=""
    )

    device_code: StringProperty(
        name="Device Code",
        description="User Device Code",
        default=""
    )

    use_mail: BoolProperty(
            name="Use mail / password",
            description="Use mail/password login or API Token",
            default=False,
    )

    use_device_code: BoolProperty(
            name="Use device code",
            description="Use device code login or API Token",
            default=True,
    )

    password: StringProperty(
        name="password",
        description="User password",
        subtype='PASSWORD',
        default="",
        update=update_tr
    )

    access_token: StringProperty(
            name="access_token",
            description="oauth access token",
            subtype='PASSWORD',
            default=""
            )

    status: StringProperty(name='', default='')
    status_type: EnumProperty(
            name="Login status type",
            items=(
                ('ERROR', "Error", ""),
                ('INFO', "Information", ""),
                ('FILE_REFRESH', "Progress", "")
            ),
            description="Determines which icon to use",
            default='FILE_REFRESH'
            )

    last_username: StringProperty(default="default")
    last_password: StringProperty(default="default")

    icosa_api = IcosaApi()

def get_available_search_domains(self, context):
    search_domains = [domain for domain in Config.ICOSA_SEARCH_DOMAIN]
    return tuple(search_domains)

def get_sorting_options(self, context):
    props = get_icosa_props()
    sort_options = Config.ICOSA_SORT_BY
    if props.search_domain != "LIKED":
        sort_options = [option for option in sort_options if option[0] != 'LIKED_TIME']
    return sort_options

class IcosaBrowserPropsProxy(bpy.types.PropertyGroup):
    # Search
    query: StringProperty(
        name="",
        update=refresh_search,
        description="Query to search",
        default="",
        options={'SKIP_SAVE'}
    )

    categories: EnumProperty(
        name="Categories",
        items=Config.ICOSA_CATEGORIES,
        description="Show only models of category",
        default='ALL',
        update=refresh_search
    )
    face_count: EnumProperty(
        name="Face Count",
        items=Config.ICOSA_FACECOUNT,
        description="Determines which meshes are exported",
        default='ANY',
        update=refresh_search
    )

    sort_by: EnumProperty(
        name="Sort by",
        items=get_sorting_options,
        description="Sort ",
        update=refresh_search,
    )

    curated: BoolProperty(
        name="Curated",
        description="Show only curated models",
        default=True,
        update=refresh_search
    )

    include_tiltbrush: BoolProperty(
        name="Open Brush Sketches",
        description="Include sketches from Open Brush (or Tilt Brush)",
        default=False,
        update=refresh_search
    )

    search_domain: EnumProperty(
        name="",
        items=get_available_search_domains,
        description="Search domain ",
        update=refresh_search
    )

    is_refreshing: BoolProperty(
        name="Refresh",
        description="Refresh",
        default=False,
    )
    expanded_filters: bpy.props.BoolProperty(default=False)

class IcosaBrowserProps(bpy.types.PropertyGroup):
    # Search
    query: StringProperty(
        name="Search",
        description="Query to search",
        default=""
    )

    categories: EnumProperty(
        name="Categories",
        items=Config.ICOSA_CATEGORIES,
        description="Show only models of category",
        default='ALL',
    )

    face_count: EnumProperty(
        name="Face Count",
        items=Config.ICOSA_FACECOUNT,
        description="Determines which meshes are exported",
        default='ANY',
    )

    sort_by: EnumProperty(
        name="Sort by",
        items=get_sorting_options,
        description="Sort ",
    )

    curated: BoolProperty(
        name="Curated",
        description="Show only curated models",
        default=True,
    )

    include_tiltbrush: BoolProperty(
        name="Open Brush Sketches",
        description="Include sketches from Open Brush (or Tilt Brush)",
        default=False,
    )

    search_domain: EnumProperty(
        name="Search domain",
        items=get_available_search_domains,
        description="Search domain ",
    )

    status: StringProperty(name='status', default='idle')

    use_preview: BoolProperty(
        name="Use Preview",
        description="Show results using preview widget instead of regular buttons with thumbnails as icons",
        default=True
        )

    search_results = {}
    current_key: StringProperty(name='current', default='current')
    has_searched_next: BoolProperty(name='next', default=False)
    has_searched_prev: BoolProperty(name='prev', default=False)

    icosa_api = IcosaLoginProps.icosa_api
    custom_icons = bpy.utils.previews.new()
    has_loaded_thumbnails: BoolProperty(default=False)

    is_latest_version: IntProperty(default=-1)

    import_status: StringProperty(name='import', default='')

    manualImportBoolean: BoolProperty(
            name="Import from url",
            description="Import a downloadable model from a url",
            default=False,
            )
    manualImportPath: StringProperty(
            name="Url",
            description="Paste full model url:\n* https://icosa.gallery/view/5rf3YuZfJAW",
            default="",
            maxlen=1024,
            options={'TEXTEDIT_UPDATE'})


def list_current_results(self, context):
    icosa_props = get_icosa_props()

    # No results:
    if 'current' not in icosa_props.search_results:
        return preview_collection['default']

    if icosa_props.has_loaded_thumbnails and 'thumbnails' in preview_collection:
        return preview_collection['thumbnails']

    res = []
    missing_thumbnail = False
    if 'current' in icosa_props.search_results and len(icosa_props.search_results['current']):
        icosa_results = icosa_props.search_results['current']
        for i, result in enumerate(icosa_results):
            if result in icosa_results:
                model = icosa_results[result]
                if model.asset_id in icosa_props.custom_icons:
                    res.append((model.asset_id, model.title, "", icosa_props.custom_icons[model.asset_id].icon_id, i))
                else:
                    res.append((model.asset_id, model.title, "", preview_collection['icosa_icon']['0'].icon_id, i))
                    missing_thumbnail = True
            else:
                print('Result issue')

    # Default element to avoid having an empty preview collection
    if not res:
        res.append(('NORESULTS', 'empty', "", preview_collection['icosa_icon']['0'].icon_id, 0))

    preview_collection['thumbnails'] = tuple(res)
    icosa_props.has_loaded_thumbnails = not missing_thumbnail
    return preview_collection['thumbnails']


def draw_model_info(layout, model, context):
    ui_model_props = layout.box().column(align=True)

    row = ui_model_props.row()
    row.label(text="{}".format(model.title), icon='OBJECT_DATA')
    row.operator("wm.icosa_view", text="", icon='LINKED').asset_id = model.asset_id
    
    ui_model_props.label(text='{}'.format(model.author), icon='ARMATURE_DATA')

    if model.license:
        ui_model_props.label(text='{}'.format(model.license), icon='TEXT')
    else:
        ui_model_props.label(text='Fetching license..')

    if model.face_count:
        ui_model_stats = ui_model_props.row()
        ui_model_stats.label(text='Faces: {}'.format(Utils.humanify_number(model.face_count)), icon='MESH_DATA')
    else:
        ui_model_props.label(text='Unknown face count..')

    layout.separator()


def draw_import_button(layout, model, context):

    import_ops = layout.row()
    icosa_props = get_icosa_props()

    import_ops.enabled = icosa_props.icosa_api.is_user_logged() and bpy.context.mode == 'OBJECT'
    if not icosa_props.icosa_api.is_user_logged():
        downloadlabel = 'Log in to download models'
    elif bpy.context.mode != 'OBJECT':
        downloadlabel = "Import is available only in object mode"
    else:
        downloadlabel = "Import model"
        if model.download_size:
            downloadlabel += " ({})".format(model.download_size)
    if icosa_props.import_status:
        downloadlabel = icosa_props.import_status

    download_icon = 'IMPORT' if import_ops.enabled else 'INFO'
    import_ops.scale_y = 2.0
    import_ops.operator("wm.icosa_download", icon=download_icon, text=downloadlabel, translate=False, emboss=True).asset_id = model.asset_id


def set_log(log):
    get_icosa_props().status = f"log: {log}"


def unzip_archive(archive_path):
    if os.path.exists(archive_path):
        set_import_status('Unzipping model')
        import zipfile
        try:
            zip_ref = zipfile.ZipFile(archive_path, 'r')
            extract_dir = os.path.dirname(archive_path)
            zip_ref.extractall(extract_dir)
            zip_ref.close()
        except zipfile.BadZipFile:
            print('Error when dezipping file')
            os.remove(archive_path)
            print('Invaild zip. Try again')
            set_import_status('')
            return None, None
        return extract_dir

    else:
        print('ERROR: archive doesn\'t exist')


def run_async(func):
    from threading import Thread
    from functools import wraps

    @wraps(func)
    def async_func(*args, **kwargs):
        func_hl = Thread(target=func, args=args, kwargs=kwargs)
        func_hl.start()
        return func_hl

    return async_func


def import_model(gltf_path, asset_id, title):
    bpy.ops.wm.import_modal('INVOKE_DEFAULT', gltf_path=gltf_path, asset_id=asset_id, title=title)


def build_search_request(query, curated, include_tiltbrush, face_count, category, sort_by):

    final_query = '&name={}'.format(query) if query else ''

    if curated:
        final_query = final_query + '&curated=true'

    if not include_tiltbrush:
        final_query = final_query + '&format=-TILT'

    if sort_by == 'NEWEST':
        final_query = final_query + '&orderBy=NEWEST'
    elif sort_by == 'OLDEST':
        final_query = final_query + '&orderBy=OLDEST'
    elif sort_by == 'BEST':
        final_query = final_query + '&orderBy=BEST'
    elif sort_by == 'TRIANGLE_COUNT':
        final_query = final_query + '&orderBy=TRIANGLE_COUNT'
    elif sort_by == 'LIKED_TIME':
        final_query = final_query + '&orderBy=LIKED_TIME'
    elif sort_by == 'CREATE_TIME':
        final_query = final_query + '&orderBy=CREATE_TIME'
    elif sort_by == 'UPDATE_TIME':
        final_query = final_query + '&orderBy=UPDATE_TIME'
    elif sort_by == 'LIKES':
        final_query = final_query + '&orderBy=LIKES'
    elif sort_by == 'DOWNLOADS':
        final_query = final_query + '&orderBy=DOWNLOADS'
    elif sort_by == 'DISPLAY_NAME':
        final_query = final_query + '&orderBy=DISPLAY_NAME'
    elif sort_by == 'AUTHOR_NAME':
        final_query = final_query + '&orderBy=AUTHOR_NAME'

    if face_count == '10K':
        final_query = final_query + '&triangleCountMax=10000'
    elif face_count == '50K':
        final_query = final_query + '&triangleCountMin=10000&triangleCountMax=50000'
    elif face_count == '100K':
        final_query = final_query + '&triangleCountMin=50000&triangleCountMax=100000'
    elif face_count == '250K':
        final_query = final_query + "&triangleCountMin=100000&triangleCountMax=250000"
    elif face_count == '250KP':
        final_query = final_query + "&triangleCountMin=250000"

    if category != 'ALL':
        final_query = final_query + '&category={}'.format(category)

    return final_query


def parse_results(r, *args, **kwargs):

    ongoingSearches.discard(r.url)

    icosa_props = get_icosa_props()
    json_data = r.json()

    if 'current' in icosa_props.search_results:
        icosa_props.search_results['current'].clear()
        del icosa_props.search_results['current']

    icosa_props.search_results['current'] = OrderedDict()

    for result in list(json_data.get('assets', [])):

        # Dirty fix to avoid parsing obsolete data
        if 'current' not in icosa_props.search_results:
            return

        asset_id = result['assetId']
        icosa_props.search_results['current'][result['assetId']] = IcosaModel(result)

        if not os.path.exists(os.path.join(Config.ICOSA_THUMB_DIR, asset_id) + '.png'):
            icosa_props.icosa_api.request_thumbnail(result['thumbnail'], asset_id)
        elif asset_id not in icosa_props.custom_icons:
            icosa_props.custom_icons.load(asset_id, os.path.join(Config.ICOSA_THUMB_DIR, "{}.png".format(asset_id)), 'IMAGE')

        # Make a request to get the download_size for own models
        """
        model = icosa_props.search_results['current'][result['assetId']]
        if model.download_size is None:
            api = icosa_props.icosa_api
            def set_download_size(r, *args, **kwargs):
                json_data = r.json()
                print(json_data)
                if 'gltf' in json_data and 'size' in json_data['gltf']:
                    model.download_size = Utils.humanify_size(json_data['gltf']['size'])
            requests_get(Utils.build_download_url(assetId), headers=api.headers, hooks={'response': set_download_size})
        """

    if 'nextPageToken' in json_data and json_data['nextPageToken']:
        current_url = r.url
        # Parse the URL and remove the page_token parameter
        parsed_url = urllib.parse.urlparse(current_url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        query_params.pop('pageToken', None)
        url_without_page_token = urllib.parse.urlunparse(
            parsed_url._replace(query=urllib.parse.urlencode(query_params, doseq=True)))
        next_page = int(json_data['nextPageToken'])
        icosa_props.icosa_api.next_results_url = f"{url_without_page_token}&pageToken={next_page}"
        # This assumes page tokens are sequential integers
        # Currently true, but might change in the future
        icosa_props.icosa_api.prev_results_url = f"{url_without_page_token}&pageToken={next_page - 1}"
    else:
        icosa_props.icosa_api.next_results_url = None
        icosa_props.icosa_api.prev_results_url = None


class ThumbnailCollector(threading.Thread):
    def __init__(self, url, asset_id):
        self.url = url
        self.asset_id = asset_id
        threading.Thread.__init__(self)

    def set_url(self, url):
        self.url = url

    def run(self):
        if not self.url:
            return
        requests_get(self.url, stream=True, hooks={'response': self.handle_thumbnail})

    def handle_thumbnail(self, r, *args, **kwargs):
        if not os.path.exists(Config.ICOSA_THUMB_DIR):
            try:
                os.makedirs(Config.ICOSA_THUMB_DIR)
            except:
                pass
        thumbnail_path = os.path.join(Config.ICOSA_THUMB_DIR, self.asset_id) + '.png'

        with open(thumbnail_path, "wb") as f:
            total_length = r.headers.get('content-length')

            if total_length is None and r.content:
                f.write(r.content)
            else:
                dl = 0
                total_length = int(total_length)
                for data in r.iter_content(chunk_size=4096):
                    dl += len(data)
                    f.write(data)

        thumbnailsProgress.discard(self.asset_id)

        props = get_icosa_props()
        if self.asset_id not in props.custom_icons:
            props.custom_icons.load(self.asset_id, os.path.join(Config.ICOSA_THUMB_DIR, "{}.png".format(self.asset_id)), 'IMAGE')


class LoginModal(bpy.types.Operator):
    """Login into your account"""
    bl_idname = "wm.login_modal"
    bl_label = ""
    bl_options = {'INTERNAL'}

    is_logging: BoolProperty(default=False)
    error: BoolProperty(default=False)
    error_message: StringProperty(default='')

    def execute(self, context):
        return {'FINISHED'}

    # def handle_mail_login(self, r, *args, **kwargs):
    #     browser_props = get_icosa_props()
    #     if r.status_code == 200 and 'access_token' in r.json():
    #         browser_props.icosa_api.access_token = r.json()['access_token']
    #         login_props = get_icosa_login_props()
    #         Cache.save_key('username', login_props.email)
    #         Cache.save_key('access_token', browser_props.icosa_api.access_token)
    #
    #         browser_props.icosa_api.build_headers()
    #         set_login_status('INFO', '')
    #         browser_props.icosa_api.request_user_info()
    #
    #     else:
    #         if 'error_description' in r.json():
    #             set_login_status('ERROR', 'Failed to authenticate: bad login/password')
    #         else:
    #             set_login_status('ERROR', 'Failed to authenticate: bad login/password')
    #             print('Cannot login.\n {}'.format(r.json()))
    #
    #     self.is_logging = False

    def handle_device_login(self, r, *args, **kwargs):
        browser_props = get_icosa_props()
        if r.status_code == 200 and 'access_token' in r.json():
            browser_props.icosa_api.access_token = r.json()['access_token']
            login_props = get_icosa_login_props()
            Cache.save_key('access_token', browser_props.icosa_api.access_token)

            browser_props.icosa_api.build_headers()
            set_login_status('INFO', '')
            browser_props.icosa_api.request_user_info()

        else:
            set_login_status(f'ERROR', f'Device code failed: {r.status_code} {r.text}')
            print('Cannot login.\n {}'.format(r.json()))

        self.is_logging = False

    def handle_token_login(self, api_token):
        browser_props = get_icosa_props()
        browser_props.icosa_api.api_token = api_token
        login_props = get_icosa_login_props()
        Cache.save_key('api_token', login_props.api_token)

        browser_props.icosa_api.build_headers()
        set_login_status('INFO', '')
        browser_props.icosa_api.request_user_info()
        self.is_logging = False

    def modal(self, context, event):
        if self.error:
            self.error = False
            set_login_status('ERROR', 'Modal: {}'.format(self.error_message))
            return {"FINISHED"}

        if self.is_logging:
            set_login_status('FILE_REFRESH', 'Logging in to your Icosa Gallery account...')
            return {'RUNNING_MODAL'}
        else:
            return {'FINISHED'}

    def invoke(self, context, event):
        self.is_logging = True
        try:
            context.window_manager.modal_handler_add(self)
            login_props = get_icosa_login_props()

            # if login_props.use_mail:
            #     data = {
            #         'grant_type': 'password',
            #         # 'client_id': Config.CLIENTID,
            #         'username': login_props.email,
            #         'password': login_props.password,
            #     }
            #     requests.post(Config.ICOSA_EMAIL_AUTH, data=data, hooks={'response': self.handle_mail_login})

            if login_props.use_device_code:
                url = f"{Config.ICOSA_DEVICE_AUTH}?device_code={login_props.device_code}"
                requests.post(url, hooks={'response': self.handle_device_login})

            else:
                self.handle_token_login(login_props.api_token)
        except Exception as e:
            self.error = True
            self.error_message = str(e)

        return {'RUNNING_MODAL'}


class ImportModalOperator(bpy.types.Operator):
    """Imports the selected model into Blender"""
    bl_idname = "wm.import_modal"
    bl_label = "Import glTF model to Icosa Gallery"
    bl_options = {'INTERNAL'}

    gltf_path: StringProperty()
    asset_id: StringProperty()
    title: StringProperty()

    def execute(self, context):
        print('IMPORT')
        return {'FINISHED'}

    def modal(self, context, event):
        if bpy.context.scene.render.engine not in ["CYCLES", "BLENDER_EEVEE_NEXT"]:
            bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT"
        try:
            old_objects = [o.name for o in bpy.data.objects]  # Get the current objects in order to find the new node hierarchy

            # Blender doesn't support uv channels with 3 or 4 components
            # Legacy Tilt files from Poly are using 3 or 4 components for uv channels
            # If we prepend "_" to those channels, Blender will treat them as custom channels
            with open(self.gltf_path, 'r') as f:
                gltf_json = json.load(f)
            if "GOOGLE_tilt_brush_techniques" in gltf_json["extensions"]:
                for mesh in gltf_json["meshes"]:
                    for primitive in mesh["primitives"]:
                        # Rename the key "TEX_COORD_0" to "_TEXCOORD_0"
                        if "TEXCOORD_0" in primitive["attributes"]:
                            primitive["attributes"]["_TEXCOORD_0"] = primitive["attributes"].pop("TEXCOORD_0")
                        if "TEXCOORD_0" in primitive["attributes"]:
                            primitive["attributes"]["_TEXCOORD_1"] = primitive["attributes"].pop("TEXCOORD_0")

                with open(self.gltf_path, 'w') as f:
                    json.dump(gltf_json, f, indent=4)

            bpy.ops.import_scene.gltf(filepath=self.gltf_path)
            set_import_status('')
            Utils.clean_downloaded_model_dir(self.asset_id)
            Utils.clean_node_hierarchy([o for o in bpy.data.objects if o.name not in old_objects], self.title)
            return {'FINISHED'}
        except Exception:
            import traceback
            print(traceback.format_exc())
            set_import_status('')
            return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        set_import_status('Importing...')
        return {'RUNNING_MODAL'}


class GetRequestThread(threading.Thread):
    def __init__(self, url, callback, headers={}):
        self.url = url
        self.callback = callback
        self.headers = headers
        threading.Thread.__init__(self)

    def run(self):
        requests_get(self.url, headers=self.headers, hooks={'response': self.callback})


class View3DPanel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS' if bpy.app.version < (2, 80, 0) else 'UI'
    bl_category = 'Icosa Gallery'
    bl_context = 'objectmode'


class IcosaPanel(View3DPanel, bpy.types.Panel):
    bl_options = {'DEFAULT_CLOSED'}
    bl_idname = "VIEW3D_PT_icosa_about"
    bl_label = "About"

    @classmethod
    def poll(cls, context):
        return (context.scene is not None)

    def draw(self, context):

        icosa_props = get_icosa_props()

        if icosa_props.is_latest_version == 1:
            self.bl_label = "Icosa Gallery plugin v{} (up-to-date)".format(PLUGIN_VERSION)
        elif icosa_props.is_latest_version == 0:
            self.bl_label = "Icosa Gallery plugin v{} (outdated)".format(PLUGIN_VERSION)
            self.layout.operator('wm.icosa_new_version', text='New version available', icon='ERROR')
        elif icosa_props.is_latest_version == -2:
            self.bl_label = "Icosa Gallery plugin v{}".format(PLUGIN_VERSION)

        # External links
        #doc_ui = self.layout.row()
        self.layout.operator('wm.icosa_help', text='Documentation', icon='QUESTION')
        self.layout.operator('wm.icosa_report_issue', text='Report an issue', icon='ERROR')
        self.layout.label(text="Download folder:")
        self.layout.label(text="  " + Config.ICOSA_TEMP_DIR)


class LoginPanel(View3DPanel, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_icosa_login"
    bl_label = "Log in"

    is_logged = BoolProperty()

    def draw(self, context):
        global is_plugin_enabled
        if not is_plugin_enabled:
            self.layout.operator('wm.icosa_enable', text='Activate add-on', icon="LINKED").enable = True
        else:
            # LOGIN
            icosa_login = get_icosa_login_props()
            layout = self.layout.box().column(align=True)
            layout.enabled = get_plugin_enabled()
            if icosa_login.icosa_api.is_user_logged():
                login_row = layout.row()
                login_row.label(text='Logged in as {}'.format(icosa_login.icosa_api.get_user_info()))
                login_row.operator('wm.icosa_login', text='Logout', icon='DISCLOSURE_TRI_RIGHT').authenticate = False
                if icosa_login.status:
                    layout.prop(icosa_login, 'status', icon=icosa_login.status_type)
            else:
                layout.label(text="Login to your Icosa Gallery account", icon='INFO')
                ops_row = layout.row()
                ops_row.operator('wm.icosa_signup', text='Create an account', icon='PLUS')

                # Disabled for now
                # layout.prop(icosa_login, "use_mail")

                # The only option so no need for a checkbox
                # layout.prop(icosa_login, "use_device_code")

                if icosa_login.use_mail:
                    layout.prop(icosa_login, "email")
                    layout.prop(icosa_login, "password")
                elif icosa_login.use_device_code:
                    ops_row = layout.row()
                    ops_row.operator('wm.icosa_get_device_code', text='Get a device code', icon='PLUS')
                    layout.prop(icosa_login, "device_code")
                else:
                    layout.prop(icosa_login, "api_token")
                login_icon = "LINKED" if bpy.app.version < (2, 80, 0) else "USER"
                ops_row = layout.row()
                ops_row.operator('wm.icosa_login', text='Log in', icon=login_icon).authenticate = True
                if icosa_login.status:
                    layout.prop(icosa_login, 'status', icon=icosa_login.status_type)


class Model:
    def __init__(self, _asset_id):
        self.asset_id = _asset_id
        self.download_size = 0


class IcosaBrowse(View3DPanel, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_icosa_browse"
    bl_label = "Import"

    asset_id = ''
    label = "Search results"

    def draw_search(self, layout, context):
        prop = get_icosa_props()
        props = get_icosa_props_proxy()
        icosa_api = prop.icosa_api

        # Add an option to import from url or assetId
        col = layout.box().column(align=True)
        row = col.row()
        row.prop(prop, "manualImportBoolean")

        if prop.manualImportBoolean:
            row = col.row()
            row.prop(prop, "manualImportPath")
        
        else:
            col = layout.box().column(align=True)
            ro = col.row()
            ro.label(text="Search")
            domain_col = ro.column()
            domain_col.scale_x = 1.5
            domain_col.enabled = icosa_api.is_user_logged()
            domain_col.prop(props, "search_domain")

            ro = col.row()
            ro.scale_y = 1.25
            ro.prop(props, "query")
            ro.operator("wm.icosa_search", text="", icon='VIEWZOOM')

            # Display a collapsible box for filters
            col = layout.box().column(align=True)
            col.enabled = True
            row = col.row()
            row.prop(props, "expanded_filters", icon="TRIA_DOWN" if props.expanded_filters else "TRIA_RIGHT", icon_only=True, emboss=False)
            row.label(text="Search filters")
            if props.expanded_filters:
                col.separator()
                col.prop(props, "categories")
                col.prop(props, "sort_by")
                col.prop(props, "face_count")
                row = col.row()
                row.prop(props, "curated")
                row.prop(props, "include_tiltbrush")

        pprops = get_icosa_props()

    def draw_results(self, layout, context):

        props = get_icosa_props()

        col = layout.box().column(align=True)

        if not props.manualImportBoolean:

            #results = layout.column(align=True)
            col.label(text=self.label)

            model = None

            result_pages_ops = col.row()
            if props.icosa_api.prev_results_url:
                result_pages_ops.operator("wm.icosa_search_prev", text="Previous page", icon='FRAME_PREV')

            if props.icosa_api.next_results_url:
                result_pages_ops.operator("wm.icosa_search_next", text="Next page", icon='FRAME_NEXT')

            #result_label = 'Click below to see more results'
            #col.label(text=result_label, icon='INFO')
            try:
                col.template_icon_view(bpy.context.window_manager, 'result_previews', show_labels=True, scale=8)
            except Exception:
                print('ResultsPanel: Failed to display results')
                pass

            if 'current' not in props.search_results or not len(props.search_results['current']):
                self.label = 'No results'
                return
            else:
                self.label = "Search results"

            if "current" in props.search_results:

                if bpy.context.window_manager.result_previews not in props.search_results['current']:
                    return

                model = props.search_results['current'][bpy.context.window_manager.result_previews]

                if not model:
                    return

                if self.asset_id != model.asset_id:
                    self.asset_id = model.asset_id

                    if not model.info_requested:
                        # TODO
                        # props.icosa_api.request_model_info(model.asset_id)
                        model.info_requested = True

                draw_model_info(col, model, context)
                draw_import_button(col, model, context)
        else:
            asset_id = ""
            if "icosa.gallery" in props.manualImportPath:
                asset_id = props.manualImportPath[-32:]
            m = Model(asset_id)
            draw_import_button(col, m, context)

    def draw(self, context):
        self.layout.enabled = get_plugin_enabled()
        self.draw_search(self.layout, context)
        self.draw_results(self.layout, context)

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self, width=900, height=850)


class IcosaExportPanel(View3DPanel, bpy.types.Panel):
    #bl_idname = "wm.icosa_export" if bpy.app.version == (2, 79, 0) else "VIEW3D_PT_icosa_export"
    bl_options = {'DEFAULT_CLOSED'}
    bl_label = "Export"
    bl_idname = "VIEW3D_PT_icosa_export"

    def draw(self, context):

        api = get_icosa_props().icosa_api
        self.layout.enabled = get_plugin_enabled() and api.is_user_logged()

        wm = context.window_manager
        props = wm.icosa_export

        layout = self.layout

        # Selection only
        layout.prop(props, "selection")

        # Upload button
        row = layout.row()
        row.scale_y = 2.0
        upload_label = "Upload"
        upload_icon  = "EXPORT"
        upload_enabled = api.is_user_logged() and bpy.context.mode == 'OBJECT'
        if not upload_enabled:
            if not api.is_user_logged():
                upload_label = "Log in to upload models"
            elif bpy.context.mode != 'OBJECT':
                upload_label = "Export is only available in object mode"
        if sf_state.uploading:
            upload_label = "Uploading %s" % sf_state.size_label
            upload_icon  = "SORTTIME"
        row.operator("wm.icosa_export", icon=upload_icon, text=upload_label)

        publish_url = sf_state.publish_url
        if publish_url:
            layout.operator("wm.url_open", text="Edit or Publish", icon='URL').url = publish_url


class IcosaLogger(bpy.types.Operator):
    """Log in / out your Icosa Gallery account"""
    bl_idname = 'wm.icosa_login'
    bl_label = 'Icosa Gallery Login'
    bl_options = {'INTERNAL'}

    authenticate: BoolProperty(default=True)

    def execute(self, context):
        set_login_status('FILE_REFRESH', 'Login to your Icosa Gallery account...')
        wm = context.window_manager
        if self.authenticate:
            wm.icosa_browser.icosa_api.login(wm.icosa_api.email, wm.icosa_api.password, wm.icosa_api.api_token)
        else:
            wm.icosa_browser.icosa_api.logout()
            wm.icosa_api.password = ''
            wm.icosa_api.last_password = "default"
            set_login_status('FILE_REFRESH', '')
        return {'FINISHED'}


class IcosaModel:
    def __init__(self, json_data):
        self.title = str(json_data['displayName'])
        self.author = json_data['authorName']
        self.username = json_data['authorId']
        self.asset_id = json_data['assetId']
        self.face_count = json_data['triangleCount']
        self.license = json_data['license']
        self.download_url = None
        self.zip_archive_url = None
        self.resource_urls = []
        self.thumbnail_path = os.path.join(Config.ICOSA_THUMB_DIR, '{}.png'.format(self.asset_id))

        for f in json_data["formats"]:
            # TODO Allow selecting the format by role or "preferred" type
            if f["formatType"] == "GLB" or f["formatType"] == "GLTF2":
                print(f"Found GLTF/GLB with role: {f['role']}")
                if "zip_archive_url" in f:
                    # TODO Remove this kludge after https://github.com/icosa-foundation/icosa-gallery/issues/164 is resolved
                    if f["zip_archive_url"].startswith("https://poly.googleusercontent.com"):
                        f["zip_archive_url"] = "https://web.archive.org/web/" + f["zip_archive_url"]
                    self.zip_archive_url = f["zip_archive_url"]
                self.download_url = f["root"]["url"]
                if "resources" in f:
                    for resource in f["resources"]:
                        self.resource_urls.append(resource["url"])

        # TODO: Get download size
        self.download_size = None
        # if 'archives' in json_data and  'gltf' in json_data['archives']:
        #     if 'size' in json_data['archives']['gltf'] and json_data['archives']['gltf']['size']:
        #         self.download_size = Utils.humanify_size(json_data['archives']['gltf']['size'])
        # else:
        #     self.download_size = None

        self.info_requested = True  # We no longer need to request the model info
        self.time_url_requested = None
        self.url_expires = None


def ShowMessage(icon="INFO", title="Info", message="Information"):
    def draw(self, context):
        self.layout.label(text=message)
    print("\n{}: {}".format(icon, message))
    bpy.context.window_manager.popup_menu(draw, title = title, icon = icon)


class IcosaDownloadModel(bpy.types.Operator):
    """Import the selected model"""
    bl_idname = "wm.icosa_download"
    bl_label = "Downloading"
    bl_options = {'INTERNAL'}

    asset_id: bpy.props.StringProperty(name="assetId")

    def execute(self, context):
        icosa_api = context.window_manager.icosa_browser.icosa_api
        icosa_api.download_model(self.asset_id)
        return {'FINISHED'}


class ViewOnIcosaGallery(bpy.types.Operator):
    """Upload your model to Icosa Gallery"""
    bl_idname = "wm.icosa_view"
    bl_label = "View the model on Icosa Gallery"
    bl_options = {'INTERNAL'}

    asset_id: bpy.props.StringProperty(name="assetId")

    def execute(self, context):
        import webbrowser
        webbrowser.open('{}/view/{}'.format(Config.ICOSA_URL, self.asset_id))
        return {'FINISHED'}


def clear_search():
    icosa_props = get_icosa_props()
    icosa_props.has_loaded_thumbnails = False
    icosa_props.search_results.clear()
    icosa_props.custom_icons.clear()
    bpy.data.window_managers['WinMan']['result_previews'] = 0


class IcosaSearch(bpy.types.Operator):
    """Send a search query to Icosa Gallery
    Searches on the selected domain (all site or own models)
    and takes into accounts various search filters"""
    bl_idname = "wm.icosa_search"
    bl_label = "Search Icosa Gallery"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        # prepare request for search
        clear_search()
        icosa_props = get_icosa_props()
        icosa_props.icosa_api.prev_results_url = None
        icosa_props.icosa_api.next_results_url = None
        final_query = build_search_request(icosa_props.query, icosa_props.curated, icosa_props.include_tiltbrush, icosa_props.face_count, icosa_props.categories, icosa_props.sort_by)
        icosa_props.icosa_api.search(final_query, parse_results)
        return {'FINISHED'}


class IcosaSearchNextResults(bpy.types.Operator):
    """Loads the next batch of 24 models from the search results"""
    bl_idname = "wm.icosa_search_next"
    bl_label = "Search Icosa Gallery"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        # prepare request for search
        clear_search()
        icosa_api = get_icosa_props().icosa_api
        icosa_api.search_cursor(icosa_api.next_results_url, parse_results)
        return {'FINISHED'}


class IcosaSearchPreviousResults(bpy.types.Operator):
    """Loads the previous batch of 24 models from the search results"""
    bl_idname = "wm.icosa_search_prev"
    bl_label = "Search Icosa Gallery"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        # prepare request for search
        clear_search()
        icosa_api = get_icosa_props().icosa_api
        icosa_api.search_cursor(icosa_api.prev_results_url, parse_results)
        return {'FINISHED'}

class IcosaCreateAccount(bpy.types.Operator):
    """Create an account on icosa.gallery"""
    bl_idname = "wm.icosa_signup"
    bl_label = "Icosa Gallery"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        import webbrowser
        webbrowser.open(Config.ICOSA_SIGNUP)
        return {'FINISHED'}

class IcosaGetDeviceCode(bpy.types.Operator):
    """Get a device code from icosa.gallery"""
    bl_idname = "wm.icosa_get_device_code"
    bl_label = "Icosa Gallery"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        import webbrowser
        webbrowser.open(Config.ICOSA_GET_DEVICE_CODE)
        return {'FINISHED'}



class IcosaNewVersion(bpy.types.Operator):
    """Opens addon latest available release on github"""
    bl_idname = "wm.icosa_new_version"
    bl_label = "Icosa Gallery"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        import webbrowser
        webbrowser.open('{}/releases/latest'.format(Config.GITHUB_REPOSITORY_URL))
        return {'FINISHED'}


class IcosaReportIssue(bpy.types.Operator):
    """Open an issue on github tracker"""
    bl_idname = "wm.icosa_report_issue"
    bl_label = "Icosa Gallery"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        import webbrowser
        webbrowser.open(Config.ICOSA_REPORT_URL)
        return {'FINISHED'}


class IcosaHelp(bpy.types.Operator):
    """Opens the addon README on github"""
    bl_idname = "wm.icosa_help"
    bl_label = "Icosa Gallery"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        import webbrowser
        webbrowser.open('{}/releases/latest'.format(Config.GITHUB_REPOSITORY_URL))
        return {'FINISHED'}


def activate_plugin():
    props = get_icosa_props()
    login = get_icosa_login_props()
    login.device_code = ''

    # Fill login/access_token
    cache_data = Cache.read()
    if 'username' in cache_data:
        login.email = cache_data['username']

    if 'access_token' in cache_data:
        props.icosa_api.access_token = cache_data['access_token']
        props.icosa_api.build_headers()
        props.icosa_api.request_user_info()
        props.icosa_api.use_mail = False
        props.icosa_api.use_device_code = True
    elif 'api_token' in cache_data:
        props.icosa_api.api_token = cache_data['api_token']
        props.icosa_api.build_headers()
        props.icosa_api.request_user_info()
        props.icosa_api.use_mail = False
        props.icosa_api.use_device_code = False

    global is_plugin_enabled
    is_plugin_enabled = True

    # TODO Implement a version check
    # try:
    #     requests_get(Config.ICOSA_PLUGIN_VERSION, hooks={'response': check_plugin_version})
    # except Exception as e:
    #     print('Error when checking for version: {}'.format(e))

    run_default_search()


class IcosaEnable(bpy.types.Operator):
    """Activate the addon (checks login, cache folders...)"""
    bl_idname = "wm.icosa_enable"
    bl_label = "Icosa Gallery"
    bl_options = {'INTERNAL'}

    enable: BoolProperty(default=True)
    def execute(self, context):
        if self.enable:
            activate_plugin()

        return {'FINISHED'}


class IcosaExportProps(bpy.types.PropertyGroup):
    filepath: StringProperty(
            name="Filepath",
            description="internal use",
            default="",
            )
    selection: BoolProperty(
            name="Selection only",
            description="Determines which meshes are exported",
            default=False,
            )


class _IcosaState:
    """Singleton to store state"""
    __slots__ = (
        "uploading",
        "size_label",
        "model_url",
        "publish_url",
        "report_message",
        "report_type",
        )

    def __init__(self):
        self.uploading = False
        self.size_label = ""
        self.model_url = ""
        self.publish_url = ""
        self.report_message = ""
        self.report_type = ''

sf_state = _IcosaState()
del _IcosaState

# remove file copy
def terminate(filepath):
    print(filepath)
    os.remove(filepath)
    os.rmdir(os.path.dirname(filepath))

def upload_report(report_message, report_type):
    sf_state.report_message = report_message
    sf_state.report_type = report_type


def upload_as_multipart(filepath, filename):
    """Upload file using multipart form encoding instead of JSON"""
    props = get_icosa_props()
    api = props.icosa_api

    # Create form data
    form = {
        "files": (filename, open(filepath, 'rb'), 'application/zip')
    }

    _headers = api.headers.copy()
    # Don't set Content-Type as requests will set it automatically with the boundary

    modelUid = ""
    requestFunction = requests.post
    uploadUrl = Config.ICOSA_UPLOAD

    # Upload and parse the result
    try:
        print("Uploading to %s" % uploadUrl)
        r = requestFunction(
            uploadUrl,
            files=form,
            headers=_headers
        )
    except requests.exceptions.RequestException as e:
        return upload_report("Upload failed. Error: %s" % str(e), 'WARNING')

    if r.status_code not in [requests.codes.ok, requests.codes.created, requests.codes.no_content]:
        return upload_report("Upload failed. Error code: %s\nMessage:\n%s" % (str(r.status_code), str(r)), 'WARNING')
    else:
        try:
            result = r.json()
            sf_state.model_url = Config.ICOSA_URL + "/view/" + result["assetId"]
            sf_state.publish_url = result['publishUrl']
        except:
            sf_state.model_url = Config.ICOSA_URL + "/view/" + modelUid
            sf_state.publish_url = ""

        return upload_report("Upload complete. Available on your icosa.gallery dashboard.", 'INFO')


class ExportIcosa(bpy.types.Operator):
    """Upload your model to Icosa Gallery"""
    bl_idname = "wm.icosa_export"
    bl_label = "Upload"

    _timer = None
    _thread = None

    def modal(self, context, event):
        if event.type == 'TIMER':
            if not self._thread.is_alive():
                wm = context.window_manager
                props = wm.icosa_export

                terminate(props.filepath)

                if context.area:
                    context.area.tag_redraw()

                # forward message from upload thread
                if not sf_state.report_type:
                    sf_state.report_type = 'ERROR'
                self.report({sf_state.report_type}, sf_state.report_message)

                wm.event_timer_remove(self._timer)
                self._thread.join()
                sf_state.uploading = False
                return {'FINISHED'}

        return {'PASS_THROUGH'}

    def execute(self, context):

        if sf_state.uploading:
            self.report({'WARNING'}, "Please wait till current upload is finished")
            return {'CANCELLED'}

        wm = context.window_manager
        props = wm.icosa_export
        sf_state.model_url = ""

        # Prepare to save the file
        binary_path = bpy.app.binary_path
        script_path = os.path.dirname(os.path.realpath(__file__))
        basename, ext = os.path.splitext(bpy.data.filepath)
        if not basename:
            basename = os.path.join(basename, "temp")
        if not ext:
            ext = ".blend"
        tempdir = tempfile.mkdtemp()
        filepath = os.path.join(tempdir, "export-icosa" + ext)

        ICOSA_EXPORT_DATA_FILE = os.path.join(tempdir, "export-icosa.json")

        try:
            # save a copy of actual scene but don't interfere with the users models
            bpy.ops.wm.save_as_mainfile(filepath=filepath, compress=True, copy=True)

            with open(ICOSA_EXPORT_DATA_FILE, 'w') as s:
                json.dump({
                        "selection": props.selection,
                        }, s)

            subprocess.check_call([
                    binary_path,
                    "--background",
                    "-noaudio",
                    filepath,
                    "--python", os.path.join(script_path, "pack_for_export.py"),
                    "--", tempdir
                    ])

            os.remove(filepath)

            # read subprocess call results
            with open(ICOSA_EXPORT_DATA_FILE, 'r') as s:
                r = json.load(s)
                size = r["size"]
                props.filepath = r["filepath"]
                filename = r["filename"]

            os.remove(ICOSA_EXPORT_DATA_FILE)

        except Exception as e:
            self.report({'WARNING'}, "Error occured while preparing your file: %s" % str(e))
            return {'FINISHED'}

        # Check the generated file size against the user plans, to know if the upload will succeed
        upload_limit = Config.ICOSA_UPLOAD_LIMITS['basic']
        if size > upload_limit:
            human_size_limit    = Utils.humanify_size(upload_limit)
            human_exported_size = Utils.humanify_size(size)
            self.report({'ERROR'}, "Upload size is above your plan upload limit: %s > %s" % (human_exported_size, human_size_limit))
            return {'FINISHED'}

        sf_state.uploading = True
        sf_state.size_label = Utils.humanify_size(size)
        self._thread = threading.Thread(
                target=upload_as_multipart,
                args=(props.filepath, filename),
                )
        self._thread.start()

        wm.modal_handler_add(self)
        self._timer = wm.event_timer_add(1.0, window=context.window)
        
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)
        self._thread.join()

def get_temporary_path():

    # Get the preferences cache directory
    cachePath = bpy.context.preferences.addons[__name__.split('.')[0]].preferences.cachePath

    # The cachePath was set in the preferences
    if cachePath:
        return cachePath
    else:
        # Rely on Blender temporary directory
        if bpy.app.version == (2, 79, 0):
            if bpy.context.user_preferences.filepaths.temporary_directory:
                return bpy.context.user_preferences.filepaths.temporary_directory
            else:
                return tempfile.mkdtemp()
        else:
            if bpy.context.preferences.filepaths.temporary_directory:
                return bpy.context.preferences.filepaths.temporary_directory
            else:
                return tempfile.mkdtemp()

def updateCacheDirectory(self, context):

    # Get the cache path from the preferences, or a default temporary
    path = os.path.abspath(get_temporary_path())

    # Delete the old directory
    # Won't delete anything upon plugin intialization, only when switching path in preferences
    if Config.ICOSA_TEMP_DIR and os.path.exists(Config.ICOSA_TEMP_DIR) and os.path.isdir(Config.ICOSA_TEMP_DIR):
        shutil.rmtree(Config.ICOSA_TEMP_DIR)

    # Create the paths and directories for temporary directories
    Config.ICOSA_TEMP_DIR = os.path.join(path, "icosa_downloads")
    Config.ICOSA_THUMB_DIR = os.path.join(Config.ICOSA_TEMP_DIR, 'thumbnails')
    Config.ICOSA_MODEL_DIR = os.path.join(Config.ICOSA_TEMP_DIR, 'imports')
    if not os.path.exists(Config.ICOSA_TEMP_DIR): os.makedirs(Config.ICOSA_TEMP_DIR)
    if not os.path.exists(Config.ICOSA_THUMB_DIR): os.makedirs(Config.ICOSA_THUMB_DIR)
    if not os.path.exists(Config.ICOSA_MODEL_DIR): os.makedirs(Config.ICOSA_MODEL_DIR)

class IcosaAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__
    cachePath: StringProperty(
        name="Cache folder",
        description=(
            "Temporary directory for downloads from icosa.gallery\n"
            "Set by the OS by default, make sure to have write access\n"
            "to this directory if you set it manually"
        ),
        subtype='DIR_PATH',
        update=updateCacheDirectory
    )
    downloadHistory: StringProperty(
        name="Download history file",
        description=(
            ".csv file containing your downloads from icosa.gallery\n"
            "If valid, the name, license and url of every model you\n"
            "download through the plugin will be saved in this file"
        ),
        subtype='FILE_PATH'
    )
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "cachePath", text="Download directory")
        layout.prop(self, "downloadHistory", text="Download history (.csv)")

classes = (
    IcosaAddonPreferences,

    # Properties
    IcosaBrowserProps,
    IcosaLoginProps,
    IcosaBrowserPropsProxy,
    IcosaExportProps,

    # Panels
    LoginPanel,
    IcosaBrowse,
    IcosaExportPanel,
    IcosaPanel,

    # Operators
    IcosaEnable,
    IcosaCreateAccount,
    IcosaGetDeviceCode,
    LoginModal,
    IcosaNewVersion,
    IcosaHelp,
    IcosaReportIssue,
    IcosaSearch,
    IcosaSearchPreviousResults,
    IcosaSearchNextResults,
    ImportModalOperator,
    ViewOnIcosaGallery,
    IcosaDownloadModel,
    IcosaLogger,
    ExportIcosa,
    )

# TODO
# def check_plugin_version(request, *args, **kwargs):
#     response = request.json()
#     icosa_props = get_icosa_props()
#     if response and len(response):
#         latest_release_version = response[0]['tag_name'].replace('.', '')
#         current_version = str(bl_info['version']).replace(',', '').replace('(', '').replace(')', '').replace(' ', '')
#
#         if latest_release_version == current_version:
#             print('You are using the latest version({})'.format(response[0]['tag_name']))
#             icosa_props.is_latest_version = 1
#         else:
#             print('A new version is available: {}'.format(response[0]['tag_name']))
#             icosa_props.is_latest_version = 0
#     else:
#         print('Failed to retrieve plugin version')
#         icosa_props.is_latest_version = -2

def register():
    icosa_icon = bpy.utils.previews.new()
    icons_dir      = os.path.dirname(__file__)
    icosa_icon.load("icosa_icon", os.path.join(icons_dir, "logo.png"), 'IMAGE')
    icosa_icon.load("0",    os.path.join(icons_dir, "placeholder.png"), 'IMAGE')

    res = []
    res.append(('NORESULTS', 'empty', "", icosa_icon['0'].icon_id, 0))
    preview_collection['default'] = tuple(res)
    preview_collection['icosa_icon'] = icosa_icon
    bpy.types.WindowManager.result_previews = EnumProperty(items=list_current_results)

    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.WindowManager.icosa_browser = PointerProperty(type=IcosaBrowserProps)
    bpy.types.WindowManager.icosa_browser_proxy = PointerProperty(type=IcosaBrowserPropsProxy)
    bpy.types.WindowManager.icosa_api = PointerProperty(type=IcosaLoginProps)
    bpy.types.WindowManager.icosa_export = PointerProperty(type=IcosaExportProps)

    # If a cache path was set in preferences, use it
    updateCacheDirectory(None, context=bpy.context)

def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)

    del bpy.types.WindowManager.icosa_api
    del bpy.types.WindowManager.icosa_browser
    del bpy.types.WindowManager.icosa_browser_proxy
    del bpy.types.WindowManager.icosa_export

    bpy.utils.previews.remove(preview_collection['icosa_icon'])
    del bpy.types.WindowManager.result_previews
    Utils.clean_thumbnail_directory()


if __name__ == "__main__":
    register()
