# About

This project is a plugin for QGIS 3 to perform interactive raster georeferencing. The plugin was originally made to replace a workflow where digitizers would use Google Earth to interactively georeference a raster and the tools (move, rotate, scale...) found in that software have been reimplemented. Compared to the standard raster georeferencer tool of QGIS, which needs control points and an export, this plugin allows the visualization of the result immediately, on top of the other layers of the map. 

# Install

## From the QGIS plugin registry

In QGIS, open the "Plugins" > "Manage and install plugin" dialog. Install the "Freehand raster georeferencer" plugin.

## From Github

Use the master branch:

1. Download a ZIP of the repository or clone it using "git clone"
2. The folder with the Python files should be directly under the directory with all the QGIS plugins (for example, ~/.qgis2/python/plugins/FreehandRasterGeoreferencer)
3. Compile the assets and UI: 
    - On Windows, launch the OSGeo4W Shell. On Unix, launch a command line and make sure the PyQT tools (pyuic5 and pyrcc5) are on the PATH
    - Go to the plugin directory
    - Launch "build.bat" or "build.sh"
4. The next time QGIS is opened, the plugin should be listed in the "Plugins" > "Manage and install plugin" dialog

A legacy version for QGIS 2 is in the `qgis2` branch.

# Documentation

See http://gvellut.github.io/FreehandRasterGeoreferencer/

# Issues

Report issues at https://github.com/gvellut/FreehandRasterGeoreferencer/issues

# Limitations

- The plugin uses Qt to read and and manipulate a raster and is therefore limited to the formats supported by that library. That means almost none of the GDAL raster formats are supported and very large rasters should be avoided. Currently BMP, JPEG, PNG, TIFF can be loaded.
- This georeferencer only supports affine transformations (without shearing) and not the full set of transformation algorithms (including rubbersheeting) the standard QGIS raster georeferencer provides
- There is limited support for changing CRS: If the CRS of the map changes, you will have to adjust georeferencing of the layer in the new CRS.
- The raster layer added by this plugin does not have all the capabilities of a normal QGIS raster layer: It is limited to visualization and modification using the provided tools. However, a normal QGIS raster file, along with georerencing information, can be easily exported by the plugin and can be reloaded using the standard "Add Raster" functionality.
- The rendering of some TIFF rasters needs something more sophisticated than what the plugin offers. It is the case for example of rasters with a data type other than Byte (or 1-bit) or with a number of bands other than 1 (grayscale) or 3 (assumed to be RGB): Qt will not open them properly. To display those with the plugin, some simple pixel transformation is made, ie reduce the number of bands or scale the data to fit in a Byte but it is not as complete as what the raster renderer of QGIS offers.
    - If a pixel transformation is performed, a message _Raster content has been transformed for display in the plugin. When exporting, select the 'Only export world file' checkbox_ will be displayed when a a raster is opened. When exporting the georeferencing, unless you are fine with the pixel transformation, be sure to check the "Only export world file" in the dialog, then choose the original raster file: In that case, no image data will be exported, just the georeferencing (including rotation).
    - It is also possible to perform the pixel transformation yourself, before opening the raster with the plugin. For example, if you have a 10-band raster with band 5, 3, 6 as RGB, you can use GDAL to export a version of the raster with those bands in the correct order. Make sure the dimensions (width, length) of the raster  stay the same though. Then use that version of the raster for georeferencing with the plugin. Finally, export only the world file and select the original raster. The original raster will then have a world file.