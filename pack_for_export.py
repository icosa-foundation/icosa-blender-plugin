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

import os
import bpy
import json
import sys
import zipfile

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

ICOSA_EXPORT_TEMP_DIR = sys.argv[7]
ICOSA_EXPORT_DATA_FILE = os.path.join(ICOSA_EXPORT_TEMP_DIR, "export-icosa.json")

# Render a thumbnail of the scene
def render_thumbnail(export_settings):
    scene = bpy.context.scene

    # Store original render settings
    original_resolution_x = scene.render.resolution_x
    original_resolution_y = scene.render.resolution_y
    original_resolution_percentage = scene.render.resolution_percentage
    original_file_format = scene.render.image_settings.file_format
    original_filepath = scene.render.filepath

    # Set render settings for thumbnail
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'

    thumbnail_path = os.path.join(ICOSA_EXPORT_TEMP_DIR, "thumbnail.png")
    scene.render.filepath = thumbnail_path

    # Render the current scene
    bpy.ops.render.render(write_still=True)

    # Restore original render settings
    scene.render.resolution_x = original_resolution_x
    scene.render.resolution_y = original_resolution_y
    scene.render.resolution_percentage = original_resolution_percentage
    scene.render.image_settings.file_format = original_file_format
    scene.render.filepath = original_filepath

    return thumbnail_path

# save a copy of the current blendfile
def save_glb(export_settings):
    import time

    filepath = ICOSA_EXPORT_TEMP_DIR
    filename = time.strftime("Icosa_%Y_%m_%d_%H_%M_%S.glb",
                             time.localtime(time.time()))
    filepath = os.path.join(filepath, filename)
    
    # Export as GLB
    bpy.ops.export_scene.gltf(
        filepath=filepath,
        export_format='GLB',
        export_cameras=True,
        export_lights=True,
        use_selection=bool(export_settings['selection']),
        export_materials='EXPORT',
        export_extras=True,
        export_apply=True  # Apply modifiers
    )

    # Render thumbnail
    thumbnail_path = render_thumbnail(export_settings)

    # Zip the GLB file and thumbnail
    zip_filepath = filepath + ".zip"
    with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(filepath, filename)
        if os.path.exists(thumbnail_path):
            zipf.write(thumbnail_path, "thumbnail.png")
    zip_filename = os.path.basename(zip_filepath)
    print("----------------------------------")
    print("Packed file: ", zip_filepath)
    print("----------------------------------")
    size = os.path.getsize(zip_filepath)

    return (zip_filepath, zip_filename, size)

# change visibility statuses and pack images
def prepare_assets(export_settings):
    hidden = set()
    images = set()

    # If we did not ask to export all models, do some cleanup
    if export_settings['selection']:

        for ob in bpy.data.objects:
            if ob.type == 'MESH':
                for mat_slot in ob.material_slots:
                    if not mat_slot.material:
                        continue

                    if bpy.app.version < (2, 80, 0):
                        for tex_slot in mat_slot.material.texture_slots:
                            if not tex_slot:
                                continue
                            tex = tex_slot.texture
                            if tex.type == 'IMAGE':
                                image = tex.image
                                if image is not None:
                                    images.add(image)

                    if mat_slot.material.use_nodes:
                        nodes = mat_slot.material.node_tree.nodes
                        for n in nodes:
                            if n.type == "TEX_IMAGE":
                                if n.image is not None:
                                    images.add(n.image)

            if export_settings['selection'] and ob.type == 'MESH':
                # Add relevant objects to the list of objects to remove
                if not ob.visible_get(): # Not visible
                    hidden.add(ob)
                elif not ob.select_get(): # Visible but not selected
                    ob.hide_set(True)
                    hidden.add(ob)

    for img in images:
        if not img.packed_file:
            try:
                img.pack()
            except:
                # can fail in rare cases
                import traceback
                traceback.print_exc()

    for ob in hidden:
        bpy.data.objects.remove(ob)

    # delete unused materials and associated textures (will remove unneeded packed images)
    for m in bpy.data.meshes:
        if m.users == 0:
            bpy.data.meshes.remove(m)
    for m in bpy.data.materials:
        if m.users == 0:
            bpy.data.materials.remove(m)
    for t in bpy.data.images:
        if t.users == 0:
            bpy.data.images.remove(t)

def prepare_file(export_settings):
    prepare_assets(export_settings)
    return save_glb(export_settings)

def read_settings():
    with open(ICOSA_EXPORT_DATA_FILE, 'r') as s:
        return json.load(s)

def write_result(filepath, filename, size):
    with open(ICOSA_EXPORT_DATA_FILE, 'w') as s:
        json.dump({
                'filepath': filepath,
                'filename': filename,
                'size': size,
                }, s)

        
if __name__ == "__main__":
    try:
        export_settings = read_settings()
        filepath, filename, size = prepare_file(export_settings)
        write_result(filepath, filename, size)
    except:
        import traceback
        traceback.print_exc()
        sys.exit(1)
