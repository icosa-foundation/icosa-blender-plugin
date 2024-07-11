# <pep8-80 compliant>
"""Blender integration."""

import bpy
import os
import time
import re
from blender2poly.signin import PolySignIn
from blender2poly.importer import Importer
import threading
import tempfile
import shutil


class PolySignInOp(bpy.types.Operator):
    """Blender operator that signs in to Poly."""
    bl_idname = "poly.sign_in"
    bl_label = "Sign in to Poly"
    bl_options = { 'REGISTER' }
    sign_in = PolySignIn()
    can_cancel = False
    sign_in_thread = None

    upload_after_signin = bpy.props.BoolProperty("upload")
    reload = bpy.props.BoolProperty("reload")

    def execute(self, context):
        return { 'FINISHED' }

    def check(self, context):
        return True

    def draw(self, context):
        col = self.layout.column()
        col.label("Poly Sign In")
        col.operator("poly.sign_in_cancel", "Cancel")

    def cancel(self, context):
        print("Cancel Poly Sign In")
        # we don't want our pop up to go away if the user moves the mouse or
        # clicks
        if not PolySignInOp.can_cancel:
            print("Opening Poly Sign In Dlg")
            bpy.ops.poly.sign_in('INVOKE_DEFAULT', reload=True)

    def invoke(self, context, event):
        if not self.reload:
            PolySignInOp.can_cancel = False
            PolySignInOp.sign_in_thread = threading.Thread(target=PolySignInOp.proc)
            PolySignInOp.sign_in_thread.start()
        return context.window_manager.invoke_popup(self)

    @classmethod
    def proc(cls):
        try:
            cls.sign_in.authenticate(force_login=True)
            while not cls.sign_in.process_auth() and not cls.can_cancel:
                time.sleep(1)
        except Exception as e:
            print(str(e))
        finally:
            cls.can_cancel = True
            cls.sign_in.finish_auth()

    @classmethod
    def cancel_sign_in(cls):
        """Cancels the sign in process"""
        cls.can_cancel = True
        cls.sign_in_thread.join()


class PolyExporterOp(bpy.types.Operator):
    """Blender operator that exports to Poly."""
    bl_idname = "poly.export"
    bl_label = "Export to Poly"
    bl_options = { 'REGISTER' }

    export_selection = bpy.props.BoolProperty(name="Selection Only", default=False)

    # progress status
    current_file = ""
    current_file_num = 0
    total_file_count = 0

    run_import_thread = False

    importer_operation = None

    def execute(self, context):
        if not self.begin_operation():
            return {'FINISHED'}

        context.window_manager.progress_begin(0.0, 1.0)

        # run a timer event every second
        self._timer = context.window_manager.event_timer_add(2.0, context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def begin_operation(self):
        """Begins the import operation."""

        # Ask Blender to export OBJ and MTL to a temp directory.
        print("Exporting.")
        self.tmp_dir = tmp_dir = tempfile.mkdtemp()
        obj_path = tmp_dir + "\\blender_export.obj"
        mtl_path = tmp_dir + "\\blender_export.mtl"
        print("Exporting OBJ/MTL.")

        if self.export_selection and not bpy.context.selected_objects:
            self.report({'ERROR'}, "Nothing selected")
            return False

        bpy.ops.export_scene.obj(filepath=obj_path, use_uvs = True, use_selection = self.export_selection)

        resource_files = [mtl_path]

        # get the paths to the texture files
        # We are going to iterate over the whole material file to find the
        # map_* lines so we can get the textures
        # additionally blender will output full paths to the textures so we
        # need to chop those full paths off to just the file name otherwise
        # poly gets confused
        mtl_file = open(mtl_path)
        mtl_file_lines = ''
        for mtl_file_line in mtl_file:
            if mtl_file_line.startswith('map_'):
                split_line = mtl_file_line.split(" ")
                print(split_line)
                #this will be the filename of the texture that we find at the
                #end of the map_* line
                texture_filename = ''
                line_str = split_line[0]
                i = 1
                while i < len(split_line):
                    current_param = split_line[i]
                    # the map_ line may have some options with parameters so we
                    # must skip those
                    # these options have 1 parameter
                    if current_param == "-blendu" or current_param == "-blendv" or current_param == "-cc" or current_param == "-clamp" or current_param == "-texres" or current_param == "-boost" or current_param == "-bm" or current_param == "-imfchan":
                        line_str += " " + " ".join(split_line[i:i + 2])
                        i += 1
                    # this one has 2
                    elif current_param == "-mm":
                        line_str += " " + " ".join(split_line[i:i + 3])
                        i += 2
                    # these have 3
                    elif current_param == "-o" or current_param == "-s" or current_param == "-t":
                        line_str += " " + " ".join(split_line[i:i + 4])
                        i += 3
                    # if no option, then this is our texture filename
                    else:
                        texture_filename += current_param + " "
                    i += 1
                    print(i)

                print("Found texture: " + texture_filename)
                # we need to remove the newline at the end, make  and make sure this
                # is not a resource we already have in our list
                texture_filename = texture_filename.rstrip()
                print("Translated texture to: " + texture_filename)
                if not texture_filename in resource_files:
                    resource_files.append(texture_filename)

                #finally we remove the full path from it and place it back into
                #our file
                mtl_file_lines += line_str + " " + os.path.basename(os.path.normpath(texture_filename))
            else:
                mtl_file_lines += mtl_file_line

        mtl_file.close()

        # write our modified mtl file back out over the existing one
        mtl_file = open(mtl_path, "w")
        mtl_file.write(mtl_file_lines)
        mtl_file.close()

        total_file_size = os.path.getsize(obj_path)

        for resource_file in resource_files:
            total_file_size += os.path.getsize(resource_file)

        if total_file_size < 100000000:

            self.importer = Importer(PolySignInOp.sign_in.access_token)
            PolyExporterOp.status = None

            PolyExporterOp.run_import_thread = True
            self.importer_thread = threading.Thread(target=PolyExporterOp.importer_thread, args=[self.importer, tmp_dir, obj_path, resource_files])
            self.importer_thread.start()
        else:
            self.report({'ERROR'}, "The size of the obj, materials and texture files can't be more than 100MB")
            PolyExporterOp.cleanup(tmp_dir)
            return False

        return True

    def importer_thread(importer, root_path, obj_path, resource_files):
        print("Running import thread")

        # make sure the user is authenticated first
        try:
            PolySignInOp.sign_in.authenticate(force_login=False)
            while not PolySignInOp.sign_in.process_auth():
                time.sleep(1)
        except Exception as e:
            print("Failed to login: " + str(e))
            PolyExporterOp.run_import_thread = False
        finally:
            PolySignInOp.sign_in.finish_auth()

        # if we are not supposed to be running the thread, then exit the thread
        if not PolyExporterOp.run_import_thread: return

        importer._access_token = PolySignInOp.sign_in.access_token
        importer.start_obj_import(obj_path, resource_files, PolyExporterOp.progress_callback)

        while importer.state != Importer.STATE_FINISHED and PolyExporterOp.run_import_thread:
            try:
                PolyExporterOp.status = importer.proc()
                PolyExporterOp.importer_operation = importer.operation
                if importer.state == Importer.STATE_IMPORT_POLL:
                    time.sleep(2)
            except:
                print("Importer failed")
                PolyExporterOp.run_import_thread = False

        try:
            PolyExporterOp.cleanup(root_path)
        except:
            print("Could not cleanup temp files at %s" % root_path)

        print("Exiting import thread")

    def cleanup(root_path):
        print("Cleaning up: " + root_path)
        shutil.rmtree(root_path)


    def progress_callback(filename, file_number, total_files, bytes_sent, total_bytes):
        current_file = filename
        current_file_num = file_number
        total_file_count = total_files
        current_file_progress = float(bytes_sent) / float(total_bytes)

    def modal(self, context, event):

        PolyExportDlg.finished = False

        context.area.tag_redraw()

        if self.importer.state == Importer.STATE_FINISHED or not PolyExporterOp.run_import_thread:
            #context.window_manager.progress_end()
            context.window_manager.event_timer_remove(self._timer)
            self.importer_thread.join()
            self.set_status("Cancelled" if PolyExporterOp.cancelled else "Finished", can_cancel=False, force_new=True);
            PolyExportDlg.finished = True

            if PolyExporterOp.importer_operation:
                if PolyExporterOp.importer_operation.error:
                    self.report({'ERROR'}, "Failed to import:\n\n%s" % PolyExporterOp.importer_operation.error)
                elif PolyExporterOp.importer_operation.result and PolyExporterOp.importer_operation.result.error:
                    self.report({'ERROR'}, "Failed to import:\n\n%s" % PolyExporterOp.importer_operation.result.error)

            return {'FINISHED'}

        status = PolyExporterOp.status

        if event.type == 'ESC':
            PolyExporterOp.cancel_export()
            PolyExportDlg.finished = True

        if event.type in {'TIMER'}:
            if status is not None:
                if status.uploading:
                    #print("Uploading file {0}, {1}".format(status.upload_file,
                    #status.upload_file_progress))
                    #display the status
                    progress = "Uploading {0} - {1}%".format(status.upload_file, int(status.upload_file_progress * 100))
                    self.set_status(progress, can_cancel=True, force_new=False)
                    self.report({'OPERATOR'}, progress)
                    #context.window_manager.progress_update(status.upload_file_progress)
                else:
                    self.set_status("Importing", can_cancel=False, force_new=not PolyExporterOp.has_displayed_import)
                    PolyExporterOp.has_displayed_import = True

        return {'RUNNING_MODAL'}

    def set_status(self, status, can_cancel, force_new):
        bpy.ops.poly.exportdlg('INVOKE_DEFAULT', can_cancel=can_cancel, status=status)
        #if PolyExportDlg.instance is None or force_new:
        #    bpy.ops.poly.exportdlg('INVOKE_DEFAULT', can_cancel=can_cancel, status=status)
        #else:
        #    PolyExportDlg.instance.can_cancel = can_cancel
        #    PolyExportDlg.instance.status = status

    @classmethod
    def cancel_export(cls):
        cls.run_import_thread = False
        cls.cancelled = True

    def invoke(self, context, event):
        PolyExporterOp.cancelled = False
        PolyExporterOp.has_displayed_import = False
        PolyExporterOp.importer_operation = None
        return context.window_manager.invoke_props_dialog(self)

class PolyExportDlg(bpy.types.Operator):
    bl_idname = "poly.exportdlg"
    bl_label = "Poly Export Dialog"
    bl_options = {'INTERNAL'}

    instance = None

    status = bpy.props.StringProperty("status")
    can_cancel = bpy.props.BoolProperty("can_cancel")

    @classmethod
    def poll(cls, context):
        print("Poll")
        #context.area.tag_redraw()
        return True

    def check(self, context):
        return True

    def cancel(self, context):
        print("Cancel PolyExportDlg")
        PolyExportDlg.instance = None
        if not PolyExportDlg.finished:
            bpy.ops.poly.exportdlg('INVOKE_DEFAULT', can_cancel=self.can_cancel, status=self.status)

    def draw(self, context):
        col = self.layout.column()
        col.label("Poly Upload Status: " + self.status)
        if self.can_cancel:
            col.operator("poly.import_cancel", "Cancel")

    def invoke(self, context, event):
        PolyExportDlg.instance = self
        return context.window_manager.invoke_popup(self)

    def execute(self, context):
        return {'FINISHED'}

class PolySignInCancelOp(bpy.types.Operator):
    bl_idname = "poly.sign_in_cancel"
    bl_label = "Poly Sign In Cancel"
    bl_options = {'INTERNAL'}

    def draw(self, context):
        col = self.layout.column()
        col.label("Cancelled Login")

    def execute(self, context):
        print("Cancel sign in")
        PolySignInOp.cancel_sign_in()
        return context.window_manager.invoke_popup(self)

class PolyImportCancelOp(bpy.types.Operator):
    bl_idname = "poly.import_cancel"
    bl_label = "Poly Import Cancel"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        print("Cancel Export")
        PolyExporterOp.cancel_export()
        PolyExportDlg.finished = True
        return {'FINISHED'}

#class PolyExportPanel(bpy.types.Panel):
#    bl_idname = "3D_VIEW_TS_polyupload"
#    bl_label = "Poly Export"
#    bl_space_type = "VIEW_3D"
#    bl_region_type = "WINDOW"
#    bl_category = "Poly"

#    def draw(self, context):
#        layout = self.layout

#        col = layout.column(align=True)
#        col.label(text="My Text")

