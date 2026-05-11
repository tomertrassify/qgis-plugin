"""
/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os.path

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QAction, QDialog, QDoubleSpinBox, QFileDialog, QLabel, QToolBar
from qgis.PyQt import sip
from qgis.core import QgsApplication, QgsMapLayer, QgsPointXY, QgsProject

from . import resources_rc  # noqa
from .freehandrastergeoreferencer_commands import ExportGeorefRasterCommand
from .freehandrastergeoreferencer_layer import (
    FreehandRasterGeoreferencerLayer,
    FreehandRasterGeoreferencerLayerType,
)
from .freehandrastergeoreferencer_maptools import (
    AdjustRasterMapTool,
    GeorefRasterBy2PointsMapTool,
    MoveRasterMapTool,
    RotateRasterMapTool,
    ScaleRasterMapTool,
)
from .freehandrastergeoreferencerdialog import FreehandRasterGeoreferencerDialog


class FreehandRasterGeoreferencer(object):

    PLUGIN_MENU = "&Freehand Raster Georeferencer"
    SUPPORTED_IMAGE_EXTENSIONS = [".jpg", ".bmp", ".png", ".tif", ".tiff", ".pdf"]

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.layers = {}
        self.layer = None
        self.layerOriginalTransforms = {}
        QgsProject.instance().layerRemoved.connect(self.layerRemoved)
        self.iface.currentLayerChanged.connect(self.currentLayerChanged)

    def _icon(self, filename):
        return QIcon(os.path.join(self.plugin_dir, "icons", filename))

    def initGui(self):
        # Create actions
        self.actionAddLayer = QAction(
            self._icon("TablerHandStop.svg"),
            "Add raster for interactive georeferencing",
            self.iface.mainWindow(),
        )
        self.actionAddLayer.setObjectName(
            "FreehandRasterGeoreferencingLayerPlugin_AddLayer"
        )
        self.actionAddLayer.triggered.connect(self.addLayer)
        self.actionAddLayerFromCurrentRaster = QAction(
            self._icon("TablerHandStop.svg"),
            "Start freehand georeferencing with this raster",
            self.iface.mainWindow(),
        )
        self.actionAddLayerFromCurrentRaster.setObjectName(
            "FreehandRasterGeoreferencingLayerPlugin_AddLayerFromCurrentRaster"
        )
        self.actionAddLayerFromCurrentRaster.triggered.connect(
            self.addLayerFromCurrentRaster
        )

        self.actionMoveRaster = QAction(
            self._icon("TablerArrowsMove.svg"),
            "Move raster",
            self.iface.mainWindow(),
        )
        self.actionMoveRaster.setObjectName(
            "FreehandRasterGeoreferencingLayerPlugin_MoveRaster"
        )
        self.actionMoveRaster.triggered.connect(self.moveRaster)
        self.actionMoveRaster.setCheckable(True)

        self.actionRotateRaster = QAction(
            self._icon("TablerRotate2.svg"),
            "Rotate raster",
            self.iface.mainWindow(),
        )
        self.actionRotateRaster.setObjectName(
            "FreehandRasterGeoreferencingLayerPlugin_RotateRaster"
        )
        self.actionRotateRaster.triggered.connect(self.rotateRaster)
        self.actionRotateRaster.setCheckable(True)

        self.actionScaleRaster = QAction(
            self._icon("TablerArrowsDiagonal.svg"),
            "Scale raster",
            self.iface.mainWindow(),
        )
        self.actionScaleRaster.setObjectName(
            "FreehandRasterGeoreferencingLayerPlugin_ScaleRaster"
        )
        self.actionScaleRaster.triggered.connect(self.scaleRaster)
        self.actionScaleRaster.setCheckable(True)

        self.actionAdjustRaster = QAction(
            self._icon("TablerArrowsHorizontal.svg"),
            "Adjust sides of raster",
            self.iface.mainWindow(),
        )
        self.actionAdjustRaster.setObjectName(
            "FreehandRasterGeoreferencingLayerPlugin_AdjustRaster"
        )
        self.actionAdjustRaster.triggered.connect(self.adjustRaster)
        self.actionAdjustRaster.setCheckable(True)

        self.actionGeoref2PRaster = QAction(
            self._icon("TablerMapPins.svg"),
            "Georeference raster with 2 points",
            self.iface.mainWindow(),
        )
        self.actionGeoref2PRaster.setObjectName(
            "FreehandRasterGeoreferencingLayerPlugin_Georef2PRaster"
        )
        self.actionGeoref2PRaster.triggered.connect(self.georef2PRaster)
        self.actionGeoref2PRaster.setCheckable(True)

        self.actionIncreaseTransparency = QAction(
            self._icon("TablerPlus.svg"),
            "Increase transparency",
            self.iface.mainWindow(),
        )
        self.actionIncreaseTransparency.triggered.connect(self.increaseTransparency)
        self.actionIncreaseTransparency.setShortcut("Alt+Ctrl+N")

        self.actionDecreaseTransparency = QAction(
            self._icon("TablerMinus.svg"),
            "Decrease transparency",
            self.iface.mainWindow(),
        )
        self.actionDecreaseTransparency.triggered.connect(self.decreaseTransparency)
        self.actionDecreaseTransparency.setShortcut("Alt+Ctrl+B")

        self.actionExport = QAction(
            self._icon("TablerDownload.svg"),
            "Quick export as GeoTIFF",
            self.iface.mainWindow(),
        )
        self.actionExport.triggered.connect(self.exportGeorefRaster)

        self.actionUndo = QAction(
            self._icon("TablerArrowBackUp.svg"),
            u"Undo",
            self.iface.mainWindow(),
        )
        self.actionUndo.triggered.connect(self.undo)

        # Add menu item for optional manual loading
        self.iface.addPluginToRasterMenu(
            FreehandRasterGeoreferencer.PLUGIN_MENU, self.actionAddLayer
        )
        self.iface.addCustomActionForLayerType(
            self.actionAddLayerFromCurrentRaster, "", QgsMapLayer.RasterLayer, True
        )

        self.spinBoxRotate = QDoubleSpinBox(self.iface.mainWindow())
        self.spinBoxRotate.setDecimals(3)
        self.spinBoxRotate.setMinimum(-180)
        self.spinBoxRotate.setMaximum(180)
        self.spinBoxRotate.setSingleStep(0.1)
        self.spinBoxRotate.setValue(0.0)
        self.spinBoxRotate.setToolTip("Rotation value (-180 to 180)")
        self.spinBoxRotate.setObjectName("FreehandRasterGeoreferencer_spinbox")
        self.spinBoxRotate.setKeyboardTracking(False)
        self.spinBoxRotate.valueChanged.connect(self.spinBoxRotateValueChangeEvent)
        self.spinBoxRotate.setFocusPolicy(Qt.ClickFocus)
        self.spinBoxRotate.focusInEvent = self.spinBoxRotateFocusInEvent
        self.transformInfoLabel = QLabel(self.iface.mainWindow())
        self.transformInfoLabel.setObjectName(
            "FreehandRasterGeoreferencer_transform_info"
        )
        self.transformInfoLabel.setToolTip(
            "Scale, rotation and displacement relative to the original state"
        )
        self.transformInfoLabel.setMinimumWidth(320)
        self.transformInfoLabel.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self._setTransformInfoPlaceholder()

        # create toolbar for this plugin
        self.toolbar = self.iface.addToolBar("Freehand raster georeferencing")
        self.toolbar.setObjectName("FreehandRasterGeoreferencerToolbar")
        self.toolbar.addAction(self.actionGeoref2PRaster)
        self.toolbar.addAction(self.actionMoveRaster)
        self.toolbar.addAction(self.actionRotateRaster)
        self.toolbar.addWidget(self.spinBoxRotate)
        self.toolbar.addWidget(self.transformInfoLabel)
        self.toolbar.addAction(self.actionScaleRaster)
        self.toolbar.addAction(self.actionAdjustRaster)
        self.toolbar.addAction(self.actionDecreaseTransparency)
        self.toolbar.addAction(self.actionIncreaseTransparency)
        self.toolbar.addAction(self.actionExport)
        self.toolbar.addAction(self.actionUndo)

        # Register plugin layer type
        self.layerType = FreehandRasterGeoreferencerLayerType(self)
        QgsApplication.pluginLayerRegistry().addPluginLayerType(self.layerType)

        self.dialogAddLayer = FreehandRasterGeoreferencerDialog()
        self.moveTool = MoveRasterMapTool(self.iface)
        self.moveTool.setAction(self.actionMoveRaster)
        self.rotateTool = RotateRasterMapTool(self.iface)
        self.rotateTool.setAction(self.actionRotateRaster)
        self.scaleTool = ScaleRasterMapTool(self.iface)
        self.scaleTool.setAction(self.actionScaleRaster)
        self.adjustTool = AdjustRasterMapTool(self.iface)
        self.adjustTool.setAction(self.actionAdjustRaster)
        self.georef2PTool = GeorefRasterBy2PointsMapTool(self.iface)
        self.georef2PTool.setAction(self.actionGeoref2PRaster)
        self.currentTool = None

        # default state for toolbar
        self.checkCurrentLayerIsPluginLayer()

    def unload(self):
        toolbar = self._find_toolbar()

        # Remove the plugin menu item and icon
        self.iface.removePluginRasterMenu(
            FreehandRasterGeoreferencer.PLUGIN_MENU, self.actionAddLayer
        )
        self.iface.removeCustomActionForLayerType(self.actionAddLayerFromCurrentRaster)

        # Unregister plugin layer type
        QgsApplication.pluginLayerRegistry().removePluginLayerType(
            FreehandRasterGeoreferencerLayer.LAYER_TYPE
        )

        QgsProject.instance().layerRemoved.disconnect(self.layerRemoved)
        self.iface.currentLayerChanged.disconnect(self.currentLayerChanged)

        if self._is_qt_object_alive(toolbar):
            self._safe_qt_call(self.iface.mainWindow().removeToolBar, toolbar)
            self._safe_qt_call(toolbar.deleteLater)
        self.toolbar = None

    def _find_toolbar(self):
        try:
            return self.iface.mainWindow().findChild(
                QToolBar,
                "FreehandRasterGeoreferencerToolbar",
            )
        except Exception:
            return self.toolbar

    def _is_qt_object_alive(self, obj):
        if obj is None:
            return False
        try:
            return not sip.isdeleted(obj)
        except Exception:
            return False

    def _safe_qt_call(self, func, *args):
        try:
            return func(*args)
        except Exception:
            return None

    def layerRemoved(self, layerId):
        if layerId in self.layerOriginalTransforms:
            del self.layerOriginalTransforms[layerId]
        if layerId in self.layers:
            del self.layers[layerId]
            self.checkCurrentLayerIsPluginLayer()

    def currentLayerChanged(self, layer):
        self.checkCurrentLayerIsPluginLayer()

    def checkCurrentLayerIsPluginLayer(self):
        layer = self.iface.activeLayer()
        if (
            layer
            and layer.type() == QgsMapLayer.PluginLayer
            and layer.pluginLayerType() == FreehandRasterGeoreferencerLayer.LAYER_TYPE
        ):
            self.actionMoveRaster.setEnabled(True)
            self.actionRotateRaster.setEnabled(True)
            self.actionScaleRaster.setEnabled(True)
            self.actionAdjustRaster.setEnabled(True)
            self.actionGeoref2PRaster.setEnabled(True)
            self.actionDecreaseTransparency.setEnabled(True)
            self.actionIncreaseTransparency.setEnabled(True)
            self.actionExport.setEnabled(True)
            self.spinBoxRotate.setEnabled(True)
            self.spinBoxRotateValueSetValue(layer.rotation)
            try:
                # self.layer is the previously selected layer
                # in case it was a FRGR layer, disconnect the spinBox
                self.layer.transformParametersChanged.disconnect()
            except Exception:
                pass
            layer.transformParametersChanged.connect(self.spinBoxRotateUpdate)
            layer.transformParametersChanged.connect(self.transformInfoUpdate)
            self.dialogAddLayer.toolButtonAdvanced.setEnabled(True)
            self.actionUndo.setEnabled(True)
            self.layer = layer
            self._registerOriginalTransform(layer)
            self.updateTransformStatus(layer)

            if self.currentTool:
                self.currentTool.reset()
                self.currentTool.setLayer(layer)
        else:
            self.actionMoveRaster.setEnabled(False)
            self.actionRotateRaster.setEnabled(False)
            self.actionScaleRaster.setEnabled(False)
            self.actionAdjustRaster.setEnabled(False)
            self.actionGeoref2PRaster.setEnabled(False)
            self.actionDecreaseTransparency.setEnabled(False)
            self.actionIncreaseTransparency.setEnabled(False)
            self.actionExport.setEnabled(False)
            self.spinBoxRotate.setEnabled(False)
            self.spinBoxRotateValueSetValue(0)
            self._setTransformInfoPlaceholder()
            try:
                self.layer.transformParametersChanged.disconnect()
            except Exception:
                pass
            self.dialogAddLayer.toolButtonAdvanced.setEnabled(False)
            self.actionUndo.setEnabled(False)
            self.layer = None

            if self.currentTool:
                self.currentTool.reset()
                self.currentTool.setLayer(None)
                self._uncheckCurrentTool()

    def _registerOriginalTransform(self, layer):
        if layer.id() in self.layerOriginalTransforms:
            return

        self.layerOriginalTransforms[layer.id()] = {
            "center": QgsPointXY(layer.center.x(), layer.center.y()),
            "rotation": layer.rotation,
            "xScale": layer.xScale,
            "yScale": layer.yScale,
        }

    def _normalizeAngle(self, angle):
        while angle <= -180:
            angle += 360
        while angle > 180:
            angle -= 360
        return angle

    def _setTransformInfoPlaceholder(self):
        self.transformInfoLabel.setText("Scale: -- | Rot: -- | dX: -- | dY: --")

    def _setTransformInfoText(self, scalePercent, rotationDelta, dx, dy):
        self.transformInfoLabel.setText(
            "Scale: %.1f%% | Rot: %.2f deg | dX: %.2f | dY: %.2f"
            % (scalePercent, rotationDelta, dx, dy)
        )

    def updateTransformStatus(
        self, layer=None, center=None, rotation=None, xScale=None, yScale=None
    ):
        if not self.transformInfoLabel:
            return

        if layer is None:
            layer = self.layer
        if (
            layer is None
            or layer.type() != QgsMapLayer.PluginLayer
            or layer.pluginLayerType() != FreehandRasterGeoreferencerLayer.LAYER_TYPE
        ):
            self._setTransformInfoPlaceholder()
            return

        self._registerOriginalTransform(layer)
        original = self.layerOriginalTransforms[layer.id()]

        center = center or layer.center
        rotation = layer.rotation if rotation is None else rotation
        xScale = layer.xScale if xScale is None else xScale
        yScale = layer.yScale if yScale is None else yScale

        originalXScale = original["xScale"]
        originalYScale = original["yScale"]
        xScaleRatio = xScale / originalXScale if originalXScale else 1.0
        yScaleRatio = yScale / originalYScale if originalYScale else 1.0
        scalePercent = ((xScaleRatio + yScaleRatio) / 2.0) * 100.0

        rotationDelta = self._normalizeAngle(rotation - original["rotation"])
        dx = center.x() - original["center"].x()
        dy = center.y() - original["center"].y()

        self._setTransformInfoText(scalePercent, rotationDelta, dx, dy)

    def transformInfoUpdate(self, newParameters):
        self.updateTransformStatus(self.layer)

    def addLayer(self):
        self.dialogAddLayer.clear(self.layer)
        self.dialogAddLayer.show()
        result = self.dialogAddLayer.exec_()
        if result == QDialog.Accepted:
            self.createFreehandRasterGeoreferencerLayer()
        elif result == FreehandRasterGeoreferencerDialog.REPLACE:
            self.replaceImage()
        elif result == FreehandRasterGeoreferencerDialog.DUPLICATE:
            self.duplicateLayer()

    def addLayerFromCurrentRaster(self):
        layer = self.iface.activeLayer()
        if layer is None or layer.type() != QgsMapLayer.RasterLayer:
            self.iface.messageBar().pushWarning(
                "Freehand Raster Georeferencer",
                "Please select a raster layer in the layer list.",
            )
            return

        imagePath = self._extractImagePathFromRasterLayer(layer)
        if imagePath is None:
            self.iface.messageBar().pushWarning(
                "Freehand Raster Georeferencer",
                "Could not detect a local JPG/BMP/PNG/TIF/PDF file path for this layer.",
            )
            return

        self.createFreehandRasterGeoreferencerLayerFromPath(imagePath)

    def _extractImagePathFromRasterLayer(self, layer):
        sourceCandidates = []

        layerSource = layer.source()
        if layerSource:
            sourceCandidates.append(layerSource)

        provider = layer.dataProvider()
        if provider:
            sourceUri = provider.dataSourceUri()
            if sourceUri:
                sourceCandidates.append(sourceUri)

        for source in sourceCandidates:
            path = source.split("|", 1)[0].strip()
            if path.lower().startswith("file://"):
                path = QUrl(path).toLocalFile()

            if self._isSupportedImagePath(path):
                return path

        return None

    def _isSupportedImagePath(self, path):
        if not path:
            return False

        path = os.path.expanduser(path)
        _, extension = os.path.splitext(path)
        extension = extension.lower()
        return os.path.isfile(path) and extension in self.SUPPORTED_IMAGE_EXTENSIONS

    def replaceImage(self):
        imagepath = self.dialogAddLayer.lineEditImagePath.text()
        imagename, _ = os.path.splitext(os.path.basename(imagepath))
        self.layer.replaceImage(imagepath, imagename)

    def duplicateLayer(self):
        layer = self.iface.activeLayer().clone()
        QgsProject.instance().addMapLayer(layer)
        self.layers[layer.id()] = layer

    def createFreehandRasterGeoreferencerLayer(self):
        imagePath = self.dialogAddLayer.lineEditImagePath.text()
        self.createFreehandRasterGeoreferencerLayerFromPath(imagePath)

    def createFreehandRasterGeoreferencerLayerFromPath(self, imagePath):
        imageName, _ = os.path.splitext(os.path.basename(imagePath))
        screenExtent = self.iface.mapCanvas().extent()

        layer = FreehandRasterGeoreferencerLayer(
            self, imagePath, imageName, screenExtent
        )
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            self.layers[layer.id()] = layer
            self.iface.setActiveLayer(layer)

    def _toggleTool(self, tool):
        if self.currentTool is tool:
            # Toggle
            self._uncheckCurrentTool()
        else:
            self.currentTool = tool
            layer = self.iface.activeLayer()
            tool.setLayer(layer)
            self.iface.mapCanvas().setMapTool(tool)

    def _uncheckCurrentTool(self):
        # Toggle
        self.iface.mapCanvas().unsetMapTool(self.currentTool)
        # replace tool with Pan
        self.iface.actionPan().trigger()
        self.currentTool = None

    def moveRaster(self):
        self._toggleTool(self.moveTool)

    def rotateRaster(self):
        self._toggleTool(self.rotateTool)

    def scaleRaster(self):
        self._toggleTool(self.scaleTool)

    def adjustRaster(self):
        self._toggleTool(self.adjustTool)

    def georef2PRaster(self):
        self._toggleTool(self.georef2PTool)

    def increaseTransparency(self):
        layer = self.iface.activeLayer()
        # clamp to 100
        tr = min(layer.transparency + 10, 100)
        layer.transparencyChanged(tr)

    def decreaseTransparency(self):
        layer = self.iface.activeLayer()
        # clamp to 0
        tr = max(layer.transparency - 10, 0)
        layer.transparencyChanged(tr)

    def exportGeorefRaster(self):
        layer = self.iface.activeLayer()
        sourcePath = layer.getAbsoluteFilepath()
        defaultExportDir = os.path.dirname(sourcePath) if sourcePath else ""
        if not os.path.isdir(defaultExportDir):
            defaultExportDir = os.path.expanduser("~")
        exportDir = QFileDialog.getExistingDirectory(
            self.iface.mainWindow(),
            "Choose folder for exported GeoTIFF",
            defaultExportDir,
        )
        if not exportDir:
            return

        sourceName, _ = os.path.splitext(os.path.basename(sourcePath))
        if not sourceName:
            sourceName = layer.name()
        exportPath = os.path.join(exportDir, sourceName + "_angepasst.tif")

        exportCommand = ExportGeorefRasterCommand(self.iface)
        exportCommand.exportGeorefRaster(
            layer,
            exportPath,
            False,
            False,
            addToProject=True,
        )

    def spinBoxRotateUpdate(self, newParameters):
        self.spinBoxRotateValueSetValue(self.layer.rotation)
        self.updateTransformStatus(self.layer)

    def spinBoxRotateValueChangeEvent(self, val):
        layer = self.layer
        layer.history.append(
            {"action": "rotation", "rotation": layer.rotation, "center": layer.center}
        )
        layer.setRotation(val)
        layer.repaint()
        layer.commitTransformParameters()

    def spinBoxRotateValueSetValue(self, val):
        # for changing only the spinbox value
        self.spinBoxRotate.valueChanged.disconnect()
        self.spinBoxRotate.setValue(val)
        self.spinBoxRotate.valueChanged.connect(self.spinBoxRotateValueChangeEvent)

    def spinBoxRotateFocusInEvent(self, event):
        # for clear 2point rubberband
        if self.currentTool:
            layer = self.iface.activeLayer()
            self.currentTool.reset()
            self.currentTool.setLayer(layer)

    def undo(self):
        layer = self.iface.activeLayer()
        if self.currentTool:
            self.currentTool.reset()  # for clear 2point rubberband
            self.currentTool.setLayer(layer)
        if len(layer.history) > 0:
            act = layer.history.pop()
            if act["action"] == "move":
                layer.setCenter(act["center"])
            elif act["action"] == "scale":
                layer.setScale(act["xScale"], act["yScale"])
            elif act["action"] == "rotation":
                layer.setRotation(act["rotation"])
                layer.setCenter(act["center"])
            elif act["action"] == "adjust":
                layer.setCenter(act["center"])
                layer.setScale(act["xScale"], act["yScale"])
            elif act["action"] == "2pointsA":
                layer.setCenter(act["center"])
            elif act["action"] == "2pointsB":
                layer.setRotation(act["rotation"])
                layer.setCenter(act["center"])
                layer.setScale(act["xScale"], act["yScale"])
                layer.setScale(act["xScale"], act["yScale"])
            layer.repaint()
            layer.commitTransformParameters()
