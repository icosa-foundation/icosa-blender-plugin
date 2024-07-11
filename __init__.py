# <pep8-80 compliant>
import bpy
import sys
import importlib
from blender2poly import blender_int, config, creds, importer, log, signin, upload

bl_info = {
    "name": "Poly Exporter (Google)",
    "author": "Google, Inc.",
    "category": "Import-Export",
}

__all__ = [
    "blender_int",
    "config",
    "creds",
    "importer",
    "log",
    "signin",
    "upload"
]

# As per
# https://wiki.blender.org/index.php/Dev:Py/Scripts/Cookbook/Code_snippets/Multi-File_packages
if "bpy" in locals():
    import imp
    imp.reload(blender_int)
    imp.reload(config)
    imp.reload(creds)
    imp.reload(importer)
    imp.reload(log)
    imp.reload(signin)
    imp.reload(upload)
    print("Reloaded submodules.")
else:
    from blender2poly import blender_int, config, creds, importer, log, signin, upload
    print("Imported submodules.")


def register():
    bpy.utils.register_class(blender_int.PolyExporterOp)
    bpy.utils.register_class(blender_int.PolySignInOp)
    bpy.utils.register_class(blender_int.PolyExportDlg)
    bpy.utils.register_class(blender_int.PolySignInCancelOp)
    bpy.utils.register_class(blender_int.PolyImportCancelOp)
    #bpy.utils.register_class(blender_int.PolyExportPanel)
    bpy.types.INFO_MT_file_export.append(menu_func_sign_in)
    bpy.types.INFO_MT_file_export.append(menu_func_upload)


def unregister():
    bpy.types.INFO_MT_file_export.remove(menu_func_sign_in)
    bpy.types.INFO_MT_file_export.remove(menu_func_upload)
    bpy.utils.unregister_class(blender_int.PolyExporterOp)
    bpy.utils.unregister_class(blender_int.PolySignInOp)
    bpy.utils.unregister_class(blender_int.PolyExportDlg)
    bpy.utils.unregister_class(blender_int.PolySignInCancelOp)
    bpy.utils.unregister_class(blender_int.PolyImportCancelOp)
    #bpy.utils.unregister_class(blender_int.PolyExportPanel)


def menu_func_sign_in(self, context):
    self.layout.operator(blender_int.PolySignInOp.bl_idname, text="Sign in to Poly...", icon='PACKAGE')


def menu_func_upload(self, context):
    self.layout.operator(blender_int.PolyExporterOp.bl_idname, text="Upload to Poly...", icon='PACKAGE')


if __name__ == "__main__":
    register()

