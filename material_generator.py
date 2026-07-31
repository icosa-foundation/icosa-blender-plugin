"""
Dynamic Blender material generator for Open Brush brushes
Uses metadata from three-icosa to create Blender materials procedurally
"""

import os
import shutil
import threading
from pathlib import PurePosixPath
from urllib.parse import quote
from urllib.request import urlopen

import bpy
from .brush_metadata import BRUSH_MATERIALS


TEXTURE_BASE_URL = (
    'https://raw.githubusercontent.com/icosa-foundation/three-icosa/'
    'main/brushes'
)
TEXTURE_CACHE_PATH = 'icosa_gallery/brush_textures'
TEXTURE_DOWNLOAD_TIMEOUT = 10
GENERATED_BRUSH_PROPERTY = 'icosa_generated_brush'
_texture_downloads = set()
_texture_downloads_lock = threading.Lock()


# Three.js blend mode constants mapped to Blender
BLEND_MODE_MAP = {
    0: 'OPAQUE',      # NoBlending
    1: 'BLEND',       # NormalBlending
    2: 'BLEND',       # AdditiveBlending (we'll set blend mode to Add)
    3: 'BLEND',       # SubtractiveBlending
    4: 'BLEND',       # MultiplyBlending
    5: 'BLEND',       # CustomBlending
}

# Three.js side constants
SIDE_MAP = {
    0: False,  # FrontSide - backface culling ON
    1: False,  # BackSide - backface culling ON (render back only)
    2: True,   # DoubleSide - backface culling OFF
}


def get_brush_metadata(brush_name):
    """
    Get metadata for a brush by name

    Args:
        brush_name: Name of the brush (with or without 'ob-' prefix)

    Returns:
        Dictionary of brush metadata or None
    """
    # Try exact match first
    if brush_name in BRUSH_MATERIALS:
        return BRUSH_MATERIALS[brush_name]

    # Try with 'ob-' prefix removed
    if brush_name.startswith('ob-'):
        name_without_prefix = brush_name[3:]
        if name_without_prefix in BRUSH_MATERIALS:
            return BRUSH_MATERIALS[name_without_prefix]

    # Try adding 'ob-' prefix
    prefixed_name = f'ob-{brush_name}'
    if prefixed_name in BRUSH_MATERIALS:
        return BRUSH_MATERIALS[prefixed_name]

    # Try case-insensitive match
    brush_name_lower = brush_name.lower()
    for key in BRUSH_MATERIALS:
        if key.lower() == brush_name_lower:
            return BRUSH_MATERIALS[key]

    return None


def create_material_from_metadata(brush_name, metadata=None):
    """
    Create a Blender material from Open Brush metadata

    Args:
        brush_name: Name for the material
        metadata: Brush metadata dictionary (if None, will look up by brush_name)

    Returns:
        Created Blender material or None
    """
    if metadata is None:
        metadata = get_brush_metadata(brush_name)

    if not metadata:
        print(f"No metadata found for brush: {brush_name}")
        return None

    # Create material
    mat_name = brush_name if not brush_name.startswith('ob-') else brush_name
    mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True

    # Clear default nodes
    nodes = mat.node_tree.nodes
    nodes.clear()

    # Create shader nodes
    output_node = nodes.new(type='ShaderNodeOutputMaterial')
    output_node.location = (300, 0)

    # Determine shader type based on metadata
    shader_node = create_shader_node(mat, metadata, nodes)
    shader_node.location = (0, 0)

    # Link shader to output
    links = mat.node_tree.links
    links.new(shader_node.outputs[0], output_node.inputs[0])

    # Apply material properties
    apply_material_properties(mat, metadata)

    # Setup textures if present
    if not setup_textures(mat, metadata, nodes, shader_node):
        print(f"Could not create material '{mat_name}': required texture missing")
        bpy.data.materials.remove(mat)
        return None

    if metadata.get('blending', 0) == 2:
        setup_additive_shader(
            mat, metadata, nodes, shader_node, output_node)

    print(f"Created material: {mat_name}")
    return mat


def create_shader_node(mat, metadata, nodes):
    """
    Create appropriate shader node based on metadata

    Args:
        mat: Blender material
        metadata: Brush metadata
        nodes: Material node tree nodes

    Returns:
        Created shader node
    """
    uniforms = metadata.get('uniforms', {})

    # Most Open Brush materials use Principled BSDF as a base
    shader = nodes.new(type='ShaderNodeBsdfPrincipled')

    # Open Brush stores the authored stroke color in the imported color attribute.
    uniform_color = (1.0, 1.0, 1.0, 1.0)
    if 'u_Color' in uniforms:
        color = uniforms['u_Color']
        if len(color) >= 3:
            alpha = color[3] if len(color) >= 4 else 1.0
            uniform_color = (color[0], color[1], color[2], alpha)

    vertex_color = nodes.new(type='ShaderNodeVertexColor')
    vertex_color.location = (-600, 0)

    color_multiply = nodes.new(type='ShaderNodeMixRGB')
    color_multiply.blend_type = 'MULTIPLY'
    color_multiply.inputs['Fac'].default_value = 1.0
    color_multiply.inputs[2].default_value = uniform_color
    color_multiply.location = (-350, 50)
    mat.node_tree.links.new(
        vertex_color.outputs['Color'], color_multiply.inputs[1])
    mat.node_tree.links.new(
        color_multiply.outputs['Color'], shader.inputs['Base Color'])

    alpha_multiply = nodes.new(type='ShaderNodeMath')
    alpha_multiply.operation = 'MULTIPLY'
    alpha_multiply.inputs[1].default_value = uniform_color[3]
    alpha_multiply.location = (-350, -150)
    mat.node_tree.links.new(
        vertex_color.outputs['Alpha'], alpha_multiply.inputs[0])
    mat.node_tree.links.new(
        alpha_multiply.outputs[0], shader.inputs['Alpha'])

    # Apply specular/shininess
    if 'u_Shininess' in uniforms:
        shininess = uniforms['u_Shininess']
        # Map shininess (0-1) to roughness (inverse)
        roughness = 1.0 - min(1.0, max(0.0, shininess))
        shader.inputs['Roughness'].default_value = roughness

    if 'u_SpecColor' in uniforms:
        # Three.js SpecColor doesn't directly map to Principled BSDF
        # We can use it to influence the specular tint
        pass  # Principled BSDF handles this differently

    # Handle emission for glowing brushes
    if 'u_EmissionGain' in uniforms:
        emission_gain = uniforms['u_EmissionGain']
        if emission_gain > 0:
            shader.inputs['Emission Strength'].default_value = emission_gain
            # Set emission color to base color
            if 'Base Color' in shader.inputs:
                base_color = shader.inputs['Base Color'].default_value
                shader.inputs['Emission Color'].default_value = base_color

    return shader


def apply_material_properties(mat, metadata):
    """
    Apply material-level properties (blend mode, transparency, etc.)

    Args:
        mat: Blender material
        metadata: Brush metadata
    """
    blending = metadata.get('blending', 0)
    transparent = metadata.get('transparent', False)
    side = metadata.get('side', 2)
    depth_write = metadata.get('depthWrite', True)

    # Set blend mode
    if transparent or blending > 0:
        mat.blend_method = 'BLEND'

    else:
        mat.blend_method = 'OPAQUE'

    # Handle alpha clipping
    if 'u_Cutoff' in metadata.get('uniforms', {}):
        cutoff = metadata['uniforms']['u_Cutoff']
        if cutoff > 0:
            mat.blend_method = 'CLIP'
            mat.alpha_threshold = cutoff

    # Set backface culling
    mat.use_backface_culling = not SIDE_MAP.get(side, True)

    # Depth write (Blender doesn't expose this directly in materials)
    # This would need to be handled at render settings level
    if not depth_write:
        mat.show_transparent_back = False


def setup_additive_shader(mat, metadata, nodes, shader_node, output_node):
    """Build a transparent-plus-emission surface for additive blending."""
    links = mat.node_tree.links

    color_alpha = nodes.new(type='ShaderNodeMixRGB')
    color_alpha.blend_type = 'MULTIPLY'
    color_alpha.inputs['Fac'].default_value = 1.0
    color_alpha.location = (0, -300)

    base_links = list(shader_node.inputs['Base Color'].links)
    if base_links:
        links.new(base_links[0].from_socket, color_alpha.inputs[1])
    else:
        color_alpha.inputs[1].default_value = (
            shader_node.inputs['Base Color'].default_value)

    alpha_links = list(shader_node.inputs['Alpha'].links)
    if alpha_links:
        links.new(alpha_links[0].from_socket, color_alpha.inputs[2])
    else:
        alpha = shader_node.inputs['Alpha'].default_value
        color_alpha.inputs[2].default_value = (alpha, alpha, alpha, alpha)

    emission = nodes.new(type='ShaderNodeEmission')
    emission.location = (250, -200)
    emission_gain = metadata.get('uniforms', {}).get('u_EmissionGain', 1.0)
    emission.inputs['Strength'].default_value = (
        emission_gain if emission_gain > 0 else 1.0)
    links.new(color_alpha.outputs['Color'], emission.inputs['Color'])

    transparent = nodes.new(type='ShaderNodeBsdfTransparent')
    transparent.location = (250, -400)

    additive = nodes.new(type='ShaderNodeAddShader')
    additive.location = (500, -250)
    links.new(transparent.outputs[0], additive.inputs[0])
    links.new(emission.outputs[0], additive.inputs[1])
    links.new(additive.outputs[0], output_node.inputs['Surface'])


def setup_textures(mat, metadata, nodes, shader_node):
    """
    Setup texture nodes based on metadata uniforms

    Args:
        mat: Blender material
        metadata: Brush metadata
        nodes: Material node tree nodes
        shader_node: Main shader node to connect textures to
    """
    uniforms = metadata.get('uniforms', {})
    links = mat.node_tree.links

    texture_offset_x = -400
    texture_offset_y = 0

    # Main texture (diffuse/albedo)
    if 'u_MainTex' in uniforms:
        tex_path = uniforms['u_MainTex']
        if tex_path and tex_path != 'None':
            tex_node = create_texture_node(nodes, tex_path, texture_offset_x, texture_offset_y)
            if tex_node is None:
                return False
            multiply_input(
                nodes, links, tex_node.outputs['Color'],
                shader_node.inputs['Base Color'],
                (texture_offset_x + 200, texture_offset_y))
            # Connect alpha if material is transparent
            if metadata.get('transparent', False):
                multiply_input(
                    nodes, links, tex_node.outputs['Alpha'],
                    shader_node.inputs['Alpha'],
                    (texture_offset_x + 400, texture_offset_y),
                    scalar=True)
            texture_offset_y -= 300

    # Bump map (normal map)
    if 'u_BumpMap' in uniforms:
        tex_path = uniforms['u_BumpMap']
        if tex_path and tex_path != 'None':
            tex_node = create_texture_node(nodes, tex_path, texture_offset_x, texture_offset_y)
            if tex_node is None:
                return False
            # Create normal map node
            normal_node = nodes.new(type='ShaderNodeNormalMap')
            normal_node.location = (texture_offset_x + 200, texture_offset_y)
            links.new(tex_node.outputs['Color'], normal_node.inputs['Color'])
            links.new(normal_node.outputs['Normal'], shader_node.inputs['Normal'])
            texture_offset_y -= 300

    # Alpha mask
    if 'u_AlphaMask' in uniforms:
        tex_path = uniforms['u_AlphaMask']
        if tex_path and tex_path != 'None':
            tex_node = create_texture_node(nodes, tex_path, texture_offset_x, texture_offset_y)
            if tex_node is None:
                return False
            multiply_input(
                nodes, links, tex_node.outputs['Color'],
                shader_node.inputs['Alpha'],
                (texture_offset_x + 200, texture_offset_y),
                scalar=True)
            texture_offset_y -= 300

    # Specular texture
    if 'u_SpecTex' in uniforms:
        tex_path = uniforms['u_SpecTex']
        if tex_path and tex_path != 'None':
            tex_node = create_texture_node(nodes, tex_path, texture_offset_x, texture_offset_y)
            if tex_node is None:
                return False
            # Use as roughness map (inverted)
            invert_node = nodes.new(type='ShaderNodeInvert')
            invert_node.location = (texture_offset_x + 200, texture_offset_y)
            links.new(tex_node.outputs['Color'], invert_node.inputs['Color'])
            links.new(invert_node.outputs['Color'], shader_node.inputs['Roughness'])
            texture_offset_y -= 300

    if uniforms.get('u_EmissionGain', 0) > 0:
        base_color_links = shader_node.inputs['Base Color'].links
        if base_color_links:
            links.new(
                base_color_links[0].from_socket,
                shader_node.inputs['Emission Color'])

    return True


def multiply_input(nodes, links, new_output, target_input, location,
                   scalar=False):
    """Multiply a socket into an input without discarding its current source."""
    existing_links = list(target_input.links)
    existing_output = existing_links[0].from_socket if existing_links else None
    for link in existing_links:
        links.remove(link)

    if scalar:
        multiply = nodes.new(type='ShaderNodeMath')
        multiply.operation = 'MULTIPLY'
    else:
        multiply = nodes.new(type='ShaderNodeMixRGB')
        multiply.blend_type = 'MULTIPLY'
        multiply.inputs['Fac'].default_value = 1.0

    multiply.location = location
    if existing_output is not None:
        links.new(existing_output, multiply.inputs[0 if scalar else 1])
    else:
        multiply.inputs[0 if scalar else 1].default_value = target_input.default_value
    links.new(new_output, multiply.inputs[1 if scalar else 2])
    links.new(
        multiply.outputs[0 if scalar else 'Color'], target_input)


def create_texture_node(nodes, texture_path, x, y):
    """
    Create an image texture node

    Args:
        nodes: Material node tree nodes
        texture_path: Path to texture (relative to three-icosa brushes directory)
        x, y: Node location

    Returns:
        Created texture node or None
    """
    image = load_texture_image(texture_path)
    if image is None:
        return None

    tex_node = nodes.new(type='ShaderNodeTexImage')
    tex_node.location = (x, y)
    tex_node.label = f"Texture: {texture_path}"
    tex_node.image = image

    return tex_node


def load_texture_image(texture_path):
    """Load a cached texture, queuing a background download when absent."""
    relative_path = PurePosixPath(texture_path)
    if relative_path.is_absolute() or '..' in relative_path.parts:
        print(f"Invalid brush texture path: {texture_path}")
        return None

    cache_root = bpy.utils.user_resource(
        'DATAFILES', path=TEXTURE_CACHE_PATH, create=True)
    cache_path = os.path.join(cache_root, *relative_path.parts)

    if not os.path.isfile(cache_path):
        queue_texture_download(texture_path, cache_path)
        print(f"Brush texture queued for download: {texture_path}")
        return None

    try:
        return bpy.data.images.load(cache_path, check_existing=True)
    except RuntimeError as error:
        print(f"Could not load brush texture {cache_path}: {error}")
        return None


def queue_texture_download(texture_path, cache_path):
    """Fetch a texture off Blender's main thread, at most once per path."""
    with _texture_downloads_lock:
        if cache_path in _texture_downloads:
            return
        _texture_downloads.add(cache_path)

    texture_url = f"{TEXTURE_BASE_URL}/{quote(texture_path, safe='/')}"

    def download():
        partial_path = f"{cache_path}.part"
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with urlopen(texture_url, timeout=TEXTURE_DOWNLOAD_TIMEOUT) as response:
                with open(partial_path, 'wb') as output:
                    shutil.copyfileobj(response, output)
            os.replace(partial_path, cache_path)
            print(f"Brush texture downloaded: {texture_path}")
        except (OSError, ValueError) as error:
            if os.path.exists(partial_path):
                os.remove(partial_path)
            print(f"Could not download brush texture {texture_path}: {error}")
        finally:
            with _texture_downloads_lock:
                _texture_downloads.discard(cache_path)

    threading.Thread(
        target=download,
        name=f"IcosaTexture-{PurePosixPath(texture_path).name}",
        daemon=True,
    ).start()


def generate_material_for_brush(brush_name):
    """
    High-level function to generate a material for a brush

    Args:
        brush_name: Name of the brush (e.g., 'BlocksBasic', 'ob-Ink', etc.)

    Returns:
        Created Blender material or None
    """
    # Remove 'ob-' prefix if present for metadata lookup
    lookup_name = brush_name[3:] if brush_name.startswith('ob-') else brush_name

    metadata = get_brush_metadata(lookup_name)
    if not metadata:
        print(f"Cannot generate material: No metadata for '{brush_name}'")
        return None

    for material in bpy.data.materials:
        if material.get(GENERATED_BRUSH_PROPERTY) == brush_name:
            print(f"Reusing generated material for '{brush_name}'")
            return material

    generated_name = f"{brush_name} [generated]"
    material = create_material_from_metadata(generated_name, metadata)
    if material is not None:
        material[GENERATED_BRUSH_PROPERTY] = brush_name
    return material


def list_available_brushes():
    """
    Get list of all brushes with metadata

    Returns:
        List of brush names
    """
    return list(BRUSH_MATERIALS.keys())


def get_brush_info(brush_name):
    """
    Get human-readable info about a brush

    Args:
        brush_name: Name of the brush

    Returns:
        Dictionary with brush info
    """
    metadata = get_brush_metadata(brush_name)
    if not metadata:
        return None

    info = {
        'name': brush_name,
        'transparent': metadata.get('transparent', False),
        'blend_mode': BLEND_MODE_MAP.get(metadata.get('blending', 0), 'UNKNOWN'),
        'double_sided': SIDE_MAP.get(metadata.get('side', 2), True),
        'has_main_texture': 'u_MainTex' in metadata.get('uniforms', {}),
        'has_normal_map': 'u_BumpMap' in metadata.get('uniforms', {}),
        'shader_files': {
            'vertex': metadata.get('vertexShader', ''),
            'fragment': metadata.get('fragmentShader', '')
        }
    }

    return info
