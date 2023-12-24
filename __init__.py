# MIT License
#
# Copyright (c) 2023 aurycat
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# History:
# 1.0 Initial release

bl_info = {
    "name": "Quick Export Collection",
    "description": "Adds a 'Quick Export Collection' option to the context (right-click) menu of collections in the Outliner. The export settings can be configured per-collection with an ini-style config file named 'QuickExportCollectionConfig' in the in-Blender text editor (one will be created automatically when you first try to quick-export something).",
    "author": "aurycat",
    "version": (1, 0),
    "blender": (4, 0, 0), # Minimum tested version. Might work with older.
    "location": "Outliner > Collection Context Menu > Quick Export Collection",
    "warning": "",
    "doc_url": "",
    "tracker_url": "https://gitlab.com/aurycat/blender-quick-export-collection",
    "support": "COMMUNITY",
    "category": "Import-Export",
}

import bpy
import configparser
from bpy.types import Operator
from os.path import join as joinpath, normpath, isdir
from io import StringIO

DEBUG_PRINTS = True

CONFIG_FILE_NAME = "QuickExportCollectionConfig"

TARGET_MENUS = [
    # Context menu (aka right-click menu) for regular Collections in the outliner
    bpy.types.OUTLINER_MT_collection,
    # Context menu for the "Scene Collection" root in the outliner
    bpy.types.OUTLINER_MT_collection_new
]

# List of exporters which are known to work correctly
# The main rule is that they need a 'use_selection' property which
# causes the exporter to only export selected objects
EXPORTERS = {
    'fbx': bpy.ops.export_scene.fbx
}


def main():
    # Invoke unregister op on an existing "install" of the plugin before
    # re-registering. Lets you press the "Run Script" button without having
    # to maually unregister or run Blender > Reload Scripts first.
    if ('quick_export_collection' in dir(bpy.ops)) and ('unregister' in dir(bpy.ops.quick_export_collection)):
        bpy.ops.quick_export_collection.unregister()
    register()


def register():
    bpy.utils.register_class(QXC_OT_export)
    bpy.utils.register_class(QXC_OT_unregister)
    for m in TARGET_MENUS:
        m.prepend(qxc_draw_menu)


def unregister():
    for m in TARGET_MENUS:
        m.remove(qxc_draw_menu)
    bpy.utils.unregister_class(QXC_OT_export)
    bpy.utils.unregister_class(QXC_OT_unregister)


class QXC_OT_unregister(Operator):
    bl_idname = "quick_export_collection.unregister"
    bl_label = "Unregister"
    bl_options = {"REGISTER"}

    def execute(self, context):
        unregister()
        return {'FINISHED'}


def qxc_draw_menu(self, context):
    layout = self.layout
    
    layout.operator(QXC_OT_export.bl_idname)
    #layout.operator(QXC_OT_unregister.bl_idname)
    layout.separator()


def get_properties_for_op(op):
    """ Get a list of all the properties (args) to a Blender operator,
        skipping some that shouldn't be allowed to be configured in
        the config file. """
    prop_iter = op.get_rna_type().properties.items()
    skip = ["rna_type", "filepath", "filter_glob", "use_active_collection", "use_selection", "batch_mode"]
    return [(k,v) for k,v in prop_iter if k not in skip]

EXPORTER_PROPERTIES = { k:get_properties_for_op(v) for k,v in EXPORTERS.items() }


def set_excluded_collections(
    lc,
    collection_names_not_exportable,
    collection_to_export,
    within_collection_to_export=False,
    within_nonexportable=False):
    """ A LayerCollection is a wrapper around a Collection with extra info specific to the
        view layer. In particular, it holds the `exclude` property (seen as the checkbox
        next to collections in the Outliner), which determines whether objects in the 
        collection can be selected and whether objects appear in `viewlayer.objects`.

        For collections outside of the collection_to_export (CTE), their exclude state
        doesn't really matter, since only objects in the CTE are selected for export.
        Since a child collection can be non-excluded (exclude=False) even if its parent
        is excluded, just set collections outside CTE to exclude=True for cleanliness.

        The CTE should be set exclude=False, of course. And for collections inside the
        CTE, set exclude=False, unless they've been marked non-exportable in the config
        file.

        Surprising behaviour of `exclude` property:
          Modifying `exclude` property has a bit of unexpected behavior. Setting exclude=True
          will set all child collections, recursively, to exclude=True too. In addition,
          their previous exclude value will be saved internally (not accessible to Python).
          Setting exclude=False will restore all child collections, recursively to their
          saved value. These recursive actions happen even if the assignment doesn't change
          the value (e.g. setting exclude=True when `exclude` is already True).

          Setting `exclude` on the root / scene LayerCollection to either value will not
          change the root, but it will have the effect of setting exclude=False, i.e. it
          will recursively restore all child collection `exclude` to their last saved value.
          That's kinda weird, and since the root can't be excluded anyway, avoid changing it.

          This function could rely on these recurisve behaviors to make it a little more
          effecient, but they seem like implementation details that could change. So I'm
          preferring to just always set every collection, in outer-to-inner order, to
          pretend like the recurisve behavior doesn't exist.

          The only "implementation detail" I'm relying on here is that a child collection
          can be exclude=False when the parent is exclude=True, which seems safe enough;
          it's been that way since Collections were introduced in 2.80
    """

    if lc.collection == collection_to_export: # Needed if collection_to_export is the root/scene collection
        within_collection_to_export = True

    if DEBUG_PRINTS:
        w_tick = "w" if within_collection_to_export else " "
        i_tick = " " if lc.exclude else "i"
        print(f"  [{w_tick}{i_tick}] {lc.name}")

    for clc in lc.children:
        if clc.collection == collection_to_export:
            clc.exclude = False
            set_excluded_collections(clc, collection_names_not_exportable, collection_to_export, True, False)
        elif within_collection_to_export:
            tmp_wne = within_nonexportable
            if not tmp_wne:
                if clc.name in collection_names_not_exportable:
                    tmp_wne = True
            clc.exclude = tmp_wne
            set_excluded_collections(clc, collection_names_not_exportable, collection_to_export, True, tmp_wne)
        else:
            clc.exclude = True
            set_excluded_collections(clc, collection_names_not_exportable, collection_to_export, False, False)
    

def find_topmost_collections(collection_names, collection):
    """ Given a starting collection and a list of collection names,
        find the topmost list of collections which contains all the
        named collections. For example, if collection_names=["B","C","E"]
        and the hierarchy is:
          A
            B
              C
              D
            E
        the output would be [B,E], since B and E include everything
        listed in collection_names, and nothing outside of that. If
        "A" was appended to that collection_names list, then the output
        would be come [A].
    """
    if collection.name in collection_names:
        return [collection]
    list = []
    for c in collection.children:
        list.extend(find_topmost_collections(collection_names, c))
    return list


def save_global_properties(context, collection_to_export):
    save = []

    for o in collection_to_export.all_objects:
        if o.hide_select or o.hide_viewport:
            save.append((o, o.hide_select, o.hide_viewport))

    # Ideally this would only check collections that actually contain objects
    # within collection_to_exportmbut since there probably aren't many collections
    # in a scene, it's easier/faster to just to include all the collections in
    # the scene. Note just doing `collection_to_export.children_recursive` isn't
    # sufficient because if collection_to_export is a child collection, the
    # parent needs these properties changed too.
    for c in context.scene.collection.children_recursive:
        if c.hide_select or c.hide_viewport:
            save.append((c, c.hide_select, c.hide_viewport))

    return save


def restore_global_properties(save):
    for oc, hide_select, hide_viewport in save:
        oc.hide_select = hide_select
        oc.hide_viewport = hide_viewport


def select_included_objects_in_collection(view_layer, collection, hidden_objects, mesh_only=False):
    """ Select set intersection between all the objects contained in
        the collection, and all the objects not excluded in the view layer.
        Also, remove any objects recorded as invisible at the beginning of export
    """

    bpy.ops.object.select_all(action = 'DESELECT')

    objects_to_export = set(collection.all_objects) & set(view_layer.objects)    
    objects_to_export -= hidden_objects

    for o in objects_to_export:
        if not mesh_only or o.type == 'MESH':
            o.select_set(True)


class QXC_OT_export(Operator):
    bl_idname = "quick_export_collection.export"
    bl_label = "Quick Export Collection"
    bl_options = {"REGISTER"}
    bl_description = "Export all objects in this collection"

    def execute(self, context):
        """ Export the active collection. Note that getting the collection that was
            right-clicked on depends on the fact that Blender automatically makes it
            the active collection as soon as the right-click menu opens.
        """

        target_obj = context.id
        # Scene collection appears as the Scene object, not its collection
        if isinstance(target_obj, bpy.types.Scene):
            target_obj = target_obj.collection
        if not isinstance(target_obj, bpy.types.Collection):
            raise RuntimeError(f"Target object is not a collection: {target_obj}")

        collection_to_export = target_obj
        
        print(f"=== Exporting collection '{collection_to_export.name}' ===")

        s = self.get_export_settings(context, collection_to_export.name)
        if s == None:
            return {'CANCELLED'}
        exporter_name, settings, collection_names_not_exportable, collection_names_requesting_join, collection_joined_mesh_names = s

        export_func = EXPORTERS[exporter_name]

        if 'use_selection' in EXPORTER_PROPERTIES[exporter_name]:
            self.report({'ERROR'},
f"Exporter '{exporter_name}' does not have a property 'use_selection' which \
is required for Quick Export Collection to work. If this exporter has a different \
name for a property of the same concept, or doesn't have that property at all, \
you'll need to edit the code to account for it.")
            return {'CANCELLED'}

        # Ignore these values if set
        settings.pop('use_active_collection', None)
        settings.pop('use_selection', None)

        print("Using settings:")
        for k,v in settings.items():
            if k not in ['use_active_collection', 'use_selection']:
                vprint = repr(v).replace("\\\\", "\\")
                print(f"  {k}={vprint}")

        if 'check_existing' not in settings:
            settings['check_existing'] = False

        # Unfortunately, 'use_active_collection' will export objects in sub-collections
        # even if they are marked excluded! So using only that filter, we can't enforce
        # 'allow_export' for a collection. It could be combined with 'use_selection', but
        # also not all exporters have a 'use_active_collection' option. Most have 'use_selection'
        # though, so it's best to solely rely on selection as a means of deciding which
        # objects to export.
        if 'use_active_collection' in EXPORTER_PROPERTIES[exporter_name]:
            settings['use_active_collection'] = False
        settings['use_selection'] = True

        # A snag in that plan is the 'hide_select' and 'hide_viewport' options of objects and
        # collections which prevent them being selected. We need to temporarily disable those
        # properties on not only every object we want to export, so we can select it, but also
        # on every collection containing those objects, since they apply recursively.
        # To make sure we can restore in case of Exceptions, only record the properties now
        # and modify them later in the try/except block. 
        saved_object_properties = save_global_properties(context, collection_to_export)

        # 'use_visible' is difficult because other actions will modify the visiblity
        # state, for example setting `exclude=False` to collections resets the contained
        # objects' "temporary" hide_viewport setting.
        hidden_objects = set()
        if 'use_visible' in settings and settings['use_visible']:
            del settings['use_visible']
            for o in collection_to_export.all_objects:
                if not o.visible_get():
                    hidden_objects.add(o)

        # Optimize the mesh joining process by only joining at the topmost collection nesting
        # level necessary. I.e. meshes only need to get joined once, not multiple times from
        # inner to outer.
        if len(collection_names_requesting_join) > 0:
            collections_to_join = find_topmost_collections(collection_names_requesting_join, collection_to_export)
        else:
            collections_to_join = []

        if len(collections_to_join) > 0:
            print("Joining meshes for collections:")
            for c in collections_to_join:
                print(f"  {c.name} --> {collection_joined_mesh_names[c.name]}")

        result = {'CANCELLED'}

        # Create a new view layer so we can modify excluded collections and selected
        # objects and then easily restore those by just deleting the view layer and going
        # back to the previous one
        # Use 'NEW' so that all viewlayer-local hide_viewport states are reset to True,
        # which is important to be able to select objects for export (hidden objects
        # can't be selected). Unfortunately this doesn't affect the global hide_viewport
        # states, hence the 'saved_object_properties' thingy.
        saved_view_layer = context.view_layer
        bpy.ops.scene.view_layer_add(type='NEW')
        new_view_layer = context.view_layer

        # Sanity check
        if new_view_layer == saved_view_layer:
            raise RuntimeError("Failed to create a new temporary ViewLayer")

        # Enter block which restores the previous view layer on exit
        try:
            if DEBUG_PRINTS:
                print(f"[DEBUG] Marking excluded collections:")

            set_excluded_collections(new_view_layer.layer_collection, collection_names_not_exportable, collection_to_export)

            # Enter block which restores the previous hide_select/hide_viewport state on exit
            try:
                for oc,_,_ in saved_object_properties:
                    oc.hide_select = False
                    oc.hide_viewport = False

                if DEBUG_PRINTS:
                    print(f"[DEBUG] Objects in '{collection_to_export.name}':")
                    # Note that hidden ("Hide in Viewport") objects are still in the viewlayer
                    # Excluding a collection is what removes objects from the viewlayer
                    viewlayer_object_names = new_view_layer.objects.keys()
                    collection_object_names = collection_to_export.all_objects.keys()
                    for on in collection_object_names:
                        in_viewlayer = on in viewlayer_object_names
                        is_hidden = bpy.data.objects[on] in hidden_objects
                        v_tick = "v" if in_viewlayer else " "
                        h_tick = "h" if is_hidden else " "
                        print(f"  [{v_tick}{h_tick}] {on}")

                joined_meshes = []
                duplicated_meshes = []
                abort_postjoin_meshes = []
                # Enter block which removes duplicated or joined meshes on exit
                try:
                    # Create joined versions of meshes in collections that were requested to be joined
                    for c in collections_to_join:
                        select_included_objects_in_collection(new_view_layer, c, hidden_objects, mesh_only=True)
                        if len(context.selected_objects) > 0:
                            if bpy.ops.object.duplicate(linked=False) != {'FINISHED'}:
                                raise RuntimeError(f"Failed to duplicate meshes (as part of making a joined mesh) in collection {c.name}. Selected objects are: {repr(context.selected_objects)}")
                            duplicated_meshes = context.selected_objects.copy()
        
                            # Make sure the active object is among the selected
                            # objects otherwise join() is unhappy
                            context.view_layer.objects.active = context.selected_objects[0]

                            if len(context.selected_objects) > 1:
                                if bpy.ops.object.join() != {'FINISHED'}:
                                    raise RuntimeError(f"Failed to join meshes in collection {c.name}. Selected objects are: {repr(context.selected_objects)}")

                            if len(context.selected_objects) != 1:
                                abort_postjoin_meshes = context.selected_objects.copy()
                                raise RuntimeError(f"After join, more than one object is selected! When joining meshes in collection {c.name}. Selected objects are: {repr(context.selected_objects)}")

                            new_joined_mesh = context.selected_objects[0]
                            new_joined_mesh.name = collection_joined_mesh_names[c.name]
                            new_joined_mesh.data.name = new_joined_mesh.name

                            if new_joined_mesh in joined_meshes:
                                raise RuntimeError(f"Duplicate in joined meshes list! When joining meshes in collection {c.name}. Duplicate object is: {repr(context.selected_objects)}")

                            joined_meshes.append(new_joined_mesh)
                            duplicated_meshes = []

                    if DEBUG_PRINTS and len(collections_to_join) > 0:
                        print(f"[DEBUG] Objects in '{collection_to_export.name}' after joining meshes:")
                        viewlayer_object_names = new_view_layer.objects.keys()
                        collection_object_names = collection_to_export.all_objects.keys()
                        joined_mesh_names = [o.name for o in joined_meshes]
                        for on in collection_object_names:
                            in_viewlayer = on in viewlayer_object_names
                            is_hidden = bpy.data.objects[on] in hidden_objects
                            is_joined_mesh = on in joined_mesh_names
                            v_tick = "v" if in_viewlayer else " "
                            h_tick = "h" if is_hidden else " "
                            j_tick = "j" if is_joined_mesh else " "
                            print(f"  [{v_tick}{h_tick}{j_tick}] {on}")

                    # Select all objects to export.
                    # If joined meshes are involved, this first selection will include both
                    # the original separate meshes *and* the joined meshes! That will be
                    # resolved in the next step
                    select_included_objects_in_collection(new_view_layer, collection_to_export, hidden_objects)

                    if DEBUG_PRINTS and len(collections_to_join) > 0:
                        print("[DEBUG] Objects selected for export (before filtering joined meshes):")
                        for o in context.selected_objects:
                            print(f"  {o.name}")

                    # Unselect everything from joined collections...
                    for c in collections_to_join:
                        for o in c.all_objects:
                            if o.type == 'MESH':
                                o.select_set(False)

                    if DEBUG_PRINTS and len(collections_to_join) > 0:
                        print("[DEBUG] Objects selected for export (filter step 1):")
                        for o in context.selected_objects:
                            print(f"  {o.name}")
                    
                    # And now re-select only the joined meshes
                    for o in joined_meshes:
                        o.select_set(True)

                    if DEBUG_PRINTS:
                        print("[DEBUG] Final objects selected for export:")
                        for o in context.selected_objects:
                            print(f"  {o.name}")

                    is_empty = (len(context.selected_objects) == 0)

                    # At last! Do the actual export! Woooo
                    result = export_func(**settings)
                    
                    if result == {'FINISHED'}:
                        msg = f"Successfully exported {collection_to_export.name} to {settings['filepath']}"
                        if is_empty:
                            self.report({'WARNING'}, "[Export is empty!] " + msg)
                        else:
                            self.report({'INFO'}, msg)

                finally:
                    # Remove any objects created by the mesh joining process
                    # If the object was already removed, calling remove (or any access of m) will
                    # raise a ReferenceError. It doesn't matter, just clean up everything we made.
                    for m in joined_meshes:
                        try: bpy.data.objects.remove(m)
                        except: pass
                    for m in duplicated_meshes:
                        try: bpy.data.objects.remove(m)
                        except: pass
                    for m in abort_postjoin_meshes:
                        try: bpy.data.objects.remove(m)
                        except: pass
            finally:
                restore_global_properties(saved_object_properties)
        finally:
            pass
            # Restore previous view layer, which restores selection and excluded collections
            context.window.view_layer = saved_view_layer
            # Delete temporary view layer
            context.scene.view_layers.remove(new_view_layer)

        return result


    def get_export_settings(self, context, collection_name):
        """ Get all the info from the config file necessary to export a particular collection.
            Will create the config file or config section if not available.
            Also returns some general info about all collections from the config file which is
            necessary for exporting the desired collection.
        """
        global EXPORTERS, EXPORTER_PROPERTIES, CONFIG_FILE_NAME

        config = configparser.ConfigParser()
        create_conf_file = False
        append_section = False

        if CONFIG_FILE_NAME in bpy.data.texts:
            txt = bpy.data.texts[CONFIG_FILE_NAME].as_string()
            if txt == "" or txt.isspace():
                create_conf_file = True
            else:
                config.read_string(txt)
        else:
            create_conf_file = True

        if not config.has_section(collection_name):
            config.add_section(collection_name)
            append_section = True

        create = (create_conf_file or append_section)

        default = config.defaults()
        # Note that accessing something in col_config will return the value
        # from defaults() if its not set directly in the col_config section.
        col_config = config[collection_name]

        if not col_config.getboolean('exportable', fallback=True):
            self.report({'ERROR'},
f"'{collection_name}' is marked unexportable in config. (The config \
file {CONFIG_FILE_NAME} can be found in the Text Edtior window.)")
            return None

        exporter_name = col_config.get('exporter', fallback="fbx")

        if exporter_name not in EXPORTERS:
            self.report({'ERROR'},
f"Unknown/unsupported exporter '{exporter_name}' for collection '{collection_name}'. \
Please adjust it in the config file {CONFIG_FILE_NAME}, which is found in the \
Text Edtior window.")
            return None

        export_filename = col_config.get('filename', fallback=f"{collection_name}.{exporter_name}")

        export_dir = col_config.get('directory', fallback="//")

        if export_dir[:2] == "./" or export_dir[:2] == ".\\":
            self.report({'WARNING'},
f"Export directory starts with \"{export_dir[:2]}\", but in Blender the way to refer \
to a path relative to the blend file is with the prefix \"//\". Using that instead.")
            export_dir = "//" + export_dir[2:]
        elif export_dir == ".":
            self.report({'WARNING'},
f"Export directory is \".\", but in Blender the way to refer to a path relative \
to the blend file is with \"//\". Using that instead.")
            export_dir = "//"

        if create_conf_file:
            self.make_new_config_file(collection_name, export_filename)
            self.report({'ERROR'},
f"[FIRST EXPORT NOTICE!] No config file was present, so one has been created \
automatically. Go to the Text Edtior window and open {CONFIG_FILE_NAME} \
to review it, make changes as necessary, then try exporting again.")
            return None
        elif append_section:
            self.append_new_section_to_config_file(collection_name, export_filename)
            self.report({'ERROR'},
f"[FIRST EXPORT NOTICE!] This collection is not listed in the exporter config \
file. A new section for '{collection_name}' has been created automatically. \
Go to the Text Edtior window and open {CONFIG_FILE_NAME} to review it, make \
changes as necessary, then try exporting again.")
            return None

        if not bpy.data.is_saved and export_dir[:2] == '//':
            self.report({'ERROR'},
f"Export directory '{export_dir}' is relative to blend file, but the blend \
file is not saved. Please save first.")
            return None

        export_dir = normpath(bpy.path.native_pathsep(bpy.path.abspath(export_dir)))
        if not isdir(export_dir):
            self.report({'ERROR'}, f"Export directory '{export_dir}' does not exist.")
            return None

        args = self.get_exporter_args_from_config(exporter_name, col_config)
        if args == None:
            return None

        collection_names_not_exportable = []
        collection_names_requesting_join = []
        collection_joined_mesh_names = {}
        for collection_name in config.sections():
            if not config.getboolean(collection_name, 'exportable', fallback=True):
                collection_names_not_exportable.append(collection_name)

            if config.getboolean(collection_name, 'join_meshes', fallback=False):
                collection_names_requesting_join.append(collection_name)
                collection_joined_mesh_names[collection_name] = config.get(collection_name, 'joined_mesh_name', fallback=collection_name)

        export_filename = bpy.path.ensure_ext(export_filename, f".{exporter_name}")
        t = str.maketrans("\\/:*?\"'<>|", "__________")
        export_filename = export_filename.translate(t)

        args['filepath'] = joinpath(export_dir, export_filename)

        return (exporter_name, args, collection_names_not_exportable, collection_names_requesting_join, collection_joined_mesh_names)


    def make_new_config_file(self, collection_name, filename):
        text = f"""\
# Settings file for Quick Export Collection addon.
#
# Each [section] header below indicates configuration for one Collection.
# The [DEFAULT] section is special; it provides defaults for any options
# not specified in another section.
#
# The supported options are:
#   exporter         - Which model format to export with. Can be changed
#                      per-collection but usually goes in [DEFAULT].
#                      Currently the only supported exporter is 'fbx'.
#   directory        - The location files are exported to. Usually goes in
#                      the [DEFAULT] section. Start the path with // to
#                      indicate a path relative to this .blend file. Example:
#                        directory = //../Assets/Models
#                      If unspecified, the default is // .
#   filename         - The output filename. If no extension is specified, the
#                      default extension for the exporter (eg. '.fbx') is used.
#                      If unspecified, the collection's name is used.
#   exportable       - If set to False, the collection cannot be exported,
#                      and it will not be included included when exporting
#                      a parent collection. If unspecified, defaults to True.
#   join_meshes      - If set to True, all meshes in this collection will be
#                      merged/joined into one during export. It even applies
#                      when exported as a sub-collection of another export.
#   joined_mesh_name - When join_meshes is True, this specifies the name of
#                      the combined mesh in the export. If not specified, the
#                      name of the collection is used.
#   use_visible      - If True, only export visible objects. Unlike join_meshes,
#                      this applies to the whole export, not just the collections
#                      it's specified on. If not specified, defaults to False.
# Additionally, any options supported by the exporter can be specified.
# For example, the fbx exporter supports the options 'object_types',
# 'use_triangles', 'embed_textures', and more."

[DEFAULT]
exporter = fbx
directory = //

[{collection_name}]
filename = {filename}
"""
        if CONFIG_FILE_NAME not in bpy.data.texts:
            bpy.data.texts.new(CONFIG_FILE_NAME)
        bpy.data.texts[CONFIG_FILE_NAME].from_string(text)


    def append_new_section_to_config_file(self, collection_name, filename):
        text = bpy.data.texts[CONFIG_FILE_NAME].as_string()
        if text[-1:] != "\n":
            text += "\n"
        text += f"""\n\
[{collection_name}]
filename = {filename}
"""
        bpy.data.texts[CONFIG_FILE_NAME].from_string(text)


    def get_exporter_args_from_config(self, exporter, config_section):
        """ For the current exporter (e.g. fbx) look at all the properties/settings/options
            it accepts, and see if there is an entry in the config file for it. If so, validate
            it to make sure its the correct type or in the allowed set of enum options.
            Returns a dictionary that is ready to be passed to the exporter operator function
            via **args.
        """
        args = {}
        for prop_name, prop in EXPORTER_PROPERTIES[exporter]:
            ty = type(prop)
            if ty == bpy.types.BoolProperty:
                try:
                    val = config_section.getboolean(prop_name)
                except ValueError:
                    self.report({'ERROR'}, f"Invalid value for config property '{prop_name}', should be a boolean")
                    return None
            elif ty == bpy.types.StringProperty:
                val = config_section.get(prop_name)
            elif ty == bpy.types.FloatProperty:
                try:
                    val = config_section.getfloat(prop_name)
                except ValueError:
                    self.report({'ERROR'}, f"Invalid value for config property '{prop_name}', should be a number")
                    return None
            elif ty == bpy.types.IntProperty:
                try:
                    val = config_section.getint(prop_name)
                except ValueError:
                    self.report({'ERROR'}, f"Invalid value for config property '{prop_name}', should be an integer (whole number)")
                    return None
            elif ty == bpy.types.EnumProperty:
                val = config_section.get(prop_name)
                if val != None:
                    options = set([i.identifier for i in prop.enum_items])
                    if prop.is_enum_flag:
                        # enum set
                        val = set(val.split(','))
                        for v in val:
                            if v not in options:
                                self.report({'ERROR'}, f"Invalid value for config property '{prop_name}', should be a comma-separated list out of {options}")
                                return None
                    else:
                        # enum single-selection
                        if val not in options:
                            self.report({'ERROR'}, f"Invalid value for config property '{prop_name}', should be one of {options}")
                            return None

            if val != None:
                args[prop_name] = val
        return args


if __name__ == "__main__":
    main()