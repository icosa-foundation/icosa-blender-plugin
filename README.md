# Icosa Gallery Blender Addon

**Directly import and export models from and to Icosa Gallery in Blender**

* [Installation](#installation)
* [Login](#login)
* [Import from Icosa Gallery](#import-a-model-from-icosa-gallery)
* [Export to Icosa Gallery](#export-a-model-to-icosa-gallery)
* [Known issues](#known-issues)
* [Report an issue](#report-an-issue)

*Based on [Blender glTF 2.0 Importer and Exporter](https://github.com/KhronosGroup/glTF-Blender-IO) from [Khronos Group](https://github.com/KhronosGroup)*
and [Blender Plugin](https://github.com/sketchfab/blender-plugin) from [Sketchfab](https://github.com/sketchfab)


## Installation

To install the addon, just download the [latest release](https://github.com/icosa-foundation/icosa-blender-plugin/releases/latest), and install it as a regular blender addon (User Preferences -> Addons -> Install from file).

After installing the addon, two optional settings are available:

* Download history: path to a .csv file used to keep track of your downloads and model licenses
* Download directory: use this directory for temporary downloads (thumbnails and models). By default, OS specific temporary paths are used, but you can set this to a different directory if you encounter errors linked to write access.

[//]: # (<p align="center"><img style="max-width:100%" src="https://user-images.githubusercontent.com/52042414/158475442-3e6c90c3-983d-4d91-8f58-f8c3d20216dc.jpg"></p>)

<br>

## Login

After installation, the addon is available in the 3D view in the tab 'Icosa Gallery' in the Properties panel (shortcut **N**) for Blender 2.80+.

Login (mandatory to import or export models) can be achieved by getting a device code and pasting it in the addon's login window. To do so, click on the **Login** button, and follow the instructions:

[//]: # (<p align="center"><img style="max-width:100%" src="https://user-images.githubusercontent.com/52042414/158475448-e229e9b3-309f-4701-bcf5-c134f6752ce5.jpg"></p>)

Your Icosa Gallery username should then be displayed upon successful login, and you will gain access to the full import and export capabilities of the addon. 

Please note that your login credentials are stored in a temporary file on your local machine (to automatically log you in when starting Blender). You can clear it by simply logging out of your Icosa Gallery account through the **Log Out** button.

<br>

## Import a model from Icosa Gallery

Once logged in, you should be able to easily import any downloadable model from Icosa Gallery. 

[//]: # (<p align="center"><img style="max-width:100%" src="https://user-images.githubusercontent.com/52042414/158475452-3bce2d73-5e46-4ce9-a4fc-f6a6a7e1904c.jpg"></p>)

To do so, run a search query and adapt the search options in the **Search filters** menu. The dropdown located above the search bar lets you specify the type of models you are browsing through:

* All site : downloadable models available under Creative Commons licenses
* Own models: can directly download models they have uploaded to their account

Clicking the **Search Results** thumbnail allows to navigate through the search results, and selecting a thumbnail gives you details before import:

[//]: # (<p align="center"><img style="max-width:100%" src="https://user-images.githubusercontent.com/52042414/158475456-0c6c1f68-10a4-4a35-997b-9b175e4accc7.jpg"></p>)

If this fits your usecase better, you can also select the "Import from url" option to import a downloadable model through its full url, formatted as "https://icosa.gallery/view/XXXXX":

[//]: # (<p align="center"><img style="max-width:100%" src="https://user-images.githubusercontent.com/52042414/158480653-568f6a91-bcd4-4009-b927-4d5ffc400658.png"></p>)

<br>

## Export a model to Icosa Gallery

You can choose to either export the currently selected model(s) or all visible models, and set some model properties, such as its title, description and tags.

You can also choose to keep the exported model as a draft (unchecking the checkbox will directly publish the model), but only **PRO** users can set their models as Private, and optionnaly protect them with a password.

[//]: # (Finally, an option is given to [reupload a model]&#40;https://help.sketchfab.com/hc/en-us/articles/203064088-Reuploading-a-Model&#41; by specifying the model's full url, formatted as "http://sketchfab.com/3d-models/model-name-XXXX" &#40;or "https://sketchfab.com/orgs/OrgName/3d-models/model-name-XXXX" for organizations' models&#41;. Make sure to double check the model link you are reuploading to before proceeding.)

[//]: # (<p align="center"><img style="max-width:100%" src="https://user-images.githubusercontent.com/52042414/158475447-010d167e-42ae-4854-879f-137adda2fa61.jpg"></p>)

### A note on material support

Not all Blender materials and shaders will get correctly exported to Icosa Gallery. As a rule of thumb, avoid complex node graphs and don't use "transformative" nodes (Gradient, ColorRamp, Multiply, MixShader...) to improve the chances of your material being correctly parsed on Icosa Gallery.

The best material support comes with the **Principled BSDF** node, having either parameters or image textures plugged into the following channels:

* Base Color
* Roughness
* Metallic
* Normal map
* Alpha
* Emission

Note that Opacity and Backface Culling parameters should be set in the **Options** tab of the material's Properties panel in order to be directly activated in Icosa Gallery's 3D settings. 

Here is an example of a compatible node graph with backface culling and alpha mode correctly set (Blender 2.80 - Eevee renderer):

[//]: # (<p align="center"><img style="max-width:100%" src="https://user-images.githubusercontent.com/52042414/64164529-b4070380-ce43-11e9-8602-995b083ac722.jpg"></p>)


## Known Issues

If none of the following description matches your problem, please feel free to [report an issue](#report-an-issue).

### Animation (import and export)

Although simple skeletal or keyframed animations should work fine, more complex animations could cause unexpected behaviour.

There is no "quick fix" for those kinds of behaviours, which are actively being worked on on our side.

### Import

Here is a list of known issues on import, as well as some possible fixes. 

Please note that the materials are being converted from Icosa Gallery to Eevee in Blender 2.80+. If a material looks wrong, using the **Node editor** could therefore help you fixing possible issues.

#### Mesh not parented to armature

Until Blender 3.0, rigged meshes did not get parented correctly to their respective armatures, resulting in non-rigged models. This behaviour is fixed by using the plugin with a version of Blender after 3.0.

#### Empty scene after import

Scale can vary a lot between different models, and models origins are not always correctly centered. As imported models are be selected after import, you can try to scale them in order to make them visible (most often, the model will need to be scaled down).

If it's not enough, try to select a mesh in the Outliner view and use numpad '.' (**View to selected** operator) to center the view on it. Modifying the range of the clip ("Clip start" and "Clip end") in the "View" tab of the Tools panel can also help for models with high scale.

#### Unexpected colors (vertex colors)

If your model displays strange color artifacts which don't seem to be caused by textures, you can try checking the model's vertex colors information (**Properties** area -> **Object data** tab -> **Vertex Colors** layer), and delete the data if present.

Vertex colors are indeed always exported in glTF files (to allow edition), and always loaded in Blender. It is possible that this data is corrupted or useless - but disabled on Icosa Gallery - explaining why the online render looked fine.

### Export

#### Transparency

Some transparency settings might not be processed correctly, and just using a **Transparent BSDF** shader or linking a texture to the **Alpha** input of a **Principled BSDF** node might not be sufficient: try to set the opacity settings in the **Properties Panel** of the Node editor, under the **Options** tab by setting the **Blend Mode** to **Alpha Clip** or **Alpha Blend**.

#### High Resolution textures

In some very specific cases, the processing of your model can crash due to "heavy" textures. 

If your model does not process correctly in Icosa Gallery and that you are using multiple high resolution textures (for instance materials with 16k textures or multiple 8k textures), you can either try to reduce the original images size or upload your model without texture and add them later in Icosa Gallery's 3D settings.

#### Texture Colorspace

As of now, textures colorspace set in Blender are not automatically converted to Icosa Gallery, and although normal maps, roughness, metalness and occlusion textures should be processed correctly, setting a diffuse texture's colorspace in Blender as "Non-Color Data" or a metalness map as "Color" (sRGB in 2.80) will be ignored.


## Report an issue

[//]: # (If you feel like you've encountered a bug not listed in the [known issues]&#40;#known-issues&#41;, or that the addon lacks an important feature, you can contact us through [Icosa Gallery's Help Center]&#40;https://help.sketchfab.com/hc/en-us/requests/new?type=exporters&subject=Blender+Plugin&#41; &#40;or directly from the addon through the **Report an issue** button&#41;.)

To help us track a possible error, please try to append the logs of Blender's console in your message:
 
* On Windows, it is available through the menu **Window** -> **Toggle system console**
* On OSX or Linux systems, you can access this data by [starting Blender from the command line](https://docs.blender.org/manual/en/dev/render/workflows/command_line.html). Outputs will then be printed in the shell from which you launched Blender.
