from qgis.core import QgsProject, QgsVectorLayer


def visible_vector_layers():
    root = QgsProject.instance().layerTreeRoot()
    layers = []
    for layer in QgsProject.instance().mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        tree_layer = root.findLayer(layer.id())
        if tree_layer and tree_layer.isVisible():
            layers.append(layer)
    return layers
