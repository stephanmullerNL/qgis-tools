r"""
NDFF-symbologie (zwaartepunten + soorten per groep) - Processing-tool.

Neemt een NDFF-laag (locatievlakken), maakt er zwaartepunten van en zet daar
regelgebaseerde symbologie op: per soortgroep een ouderregel, met daaronder
alleen de soorten die voorkomen. Levert een nieuwe puntlaag op.

Voor de niet-vogel exports (dieren, rode lijst). Verschijnt onder
Scripts > Ecologie. Installeren: bestand in
  ...\QGIS3\profiles\default\processing\scripts\
en toolbox verversen.
"""

import random

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFeatureSink,
    QgsProcessingException,
    QgsProcessingLayerPostProcessorInterface,
    QgsFeature,
    QgsWkbTypes,
    QgsRuleBasedRenderer,
    QgsSymbol,
    QgsProject,
    NULL,
)


def _build_symbology(layer, group_field, species_field, color_mode, seed):
    if seed != -1:
        random.seed(seed)

    groups = {}
    for feat in layer.getFeatures():
        g = feat[group_field]
        s = feat[species_field]
        if g is None or g == NULL or s is None or s == NULL:
            continue
        groups.setdefault(str(g), set()).add(str(s))

    def random_color():
        return QColor.fromHsv(random.randint(0, 359), random.randint(150, 230), random.randint(180, 240))

    def group_color(gi, ng):
        return QColor.fromHsv(int(360 * gi / max(ng, 1)), 200, 230)

    def shade_color(gi, ng, si, ns):
        base = 360 * gi / max(ng, 1)
        band = 70
        hue = base if ns <= 1 else base - band / 2 + band * si / (ns - 1)
        return QColor.fromHsv(int(hue % 360), 200, 230)

    def sql_eq(field, value):
        return '"{}" = \'{}\''.format(field, str(value).replace("'", "''"))

    root = QgsRuleBasedRenderer.Rule(None)
    group_names = sorted(groups.keys())
    for gi, g in enumerate(group_names):
        parent = QgsRuleBasedRenderer.Rule(None)
        parent.setLabel(str(g))
        parent.setFilterExpression(sql_eq(group_field, g))
        species = sorted(groups[g])
        for si, s in enumerate(species):
            sym = QgsSymbol.defaultSymbol(layer.geometryType())
            if color_mode == 0:
                sym.setColor(random_color())
            elif color_mode == 1:
                sym.setColor(group_color(gi, len(group_names)))
            else:
                sym.setColor(shade_color(gi, len(group_names), si, len(species)))
            child = QgsRuleBasedRenderer.Rule(sym)
            child.setLabel(str(s))
            child.setFilterExpression(sql_eq(species_field, s))
            parent.appendChild(child)
        root.appendChild(parent)

    layer.setRenderer(QgsRuleBasedRenderer(root))
    layer.triggerRepaint()
    node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
    if node is not None:
        node.setCustomProperty('showFeatureCount', True)


class _Styler(QgsProcessingLayerPostProcessorInterface):
    def __init__(self, group_field, species_field, color_mode, seed):
        super().__init__()
        self.group_field = group_field
        self.species_field = species_field
        self.color_mode = color_mode
        self.seed = seed

    def postProcessLayer(self, layer, context, feedback):
        try:
            _build_symbology(layer, self.group_field, self.species_field, self.color_mode, self.seed)
        except Exception as e:
            feedback.pushWarning('Symbologie mislukt: {}'.format(e))


class NdffSymbologyAlgorithm(QgsProcessingAlgorithm):

    INPUT = 'INPUT'
    GROUP_FIELD = 'GROUP_FIELD'
    SPECIES_FIELD = 'SPECIES_FIELD'
    CENTROIDS = 'CENTROIDS'
    COLOR_MODE = 'COLOR_MODE'
    SEED = 'SEED'
    OUTPUT = 'OUTPUT'

    COLOR_MODES = ['Willekeurig per soort', 'Eén kleur per groep', 'Tint per soort binnen groep']

    def tr(self, s):
        return QCoreApplication.translate('Processing', s)

    def createInstance(self):
        return NdffSymbologyAlgorithm()

    def name(self):
        return 'ndff_symbologie'

    def displayName(self):
        return self.tr('NDFF niet-vogels symboliseren (per soortgroep)')

    def group(self):
        return self.tr('Ecologie')

    def groupId(self):
        return 'ecologie'

    def shortHelpString(self):
        return self.tr(
            'Maakt zwaartepunten van een NDFF-laag en zet er regelgebaseerde '
            'symbologie op: per soortgroep een groep, met de soorten eronder. '
            'Levert een nieuwe puntlaag op. Voor de niet-vogel exports.'
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, self.tr('NDFF-laag')))
        self.addParameter(QgsProcessingParameterField(
            self.GROUP_FIELD, self.tr('Groepsveld'),
            parentLayerParameterName=self.INPUT, defaultValue='srtgroepen'))
        self.addParameter(QgsProcessingParameterField(
            self.SPECIES_FIELD, self.tr('Soortveld'),
            parentLayerParameterName=self.INPUT, defaultValue='soort_ned'))
        self.addParameter(QgsProcessingParameterBoolean(
            self.CENTROIDS, self.tr('Eerst zwaartepunten maken (invoer = NDFF-vlakken)'),
            defaultValue=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.COLOR_MODE, self.tr('Kleurmodus'), options=self.COLOR_MODES, defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.SEED, self.tr('Seed voor willekeur (-1 = elke keer anders)'),
            type=QgsProcessingParameterNumber.Integer, defaultValue=-1))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr('Zwaartepunten met symbologie')))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        group_field = self.parameterAsString(parameters, self.GROUP_FIELD, context)
        species_field = self.parameterAsString(parameters, self.SPECIES_FIELD, context)
        make_centroids = self.parameterAsBool(parameters, self.CENTROIDS, context)
        color_mode = self.parameterAsEnum(parameters, self.COLOR_MODE, context)
        seed = self.parameterAsInt(parameters, self.SEED, context)

        out_wkb = QgsWkbTypes.Point if make_centroids else source.wkbType()
        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context,
            source.fields(), out_wkb, source.sourceCrs())

        n = 0
        for feat in source.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            if make_centroids:
                geom = geom.centroid()
            nf = QgsFeature(source.fields())
            nf.setAttributes(feat.attributes())
            nf.setGeometry(geom)
            sink.addFeature(nf)
            n += 1
        feedback.pushInfo('{} zwaartepunten weggeschreven.'.format(n) if make_centroids
                          else '{} objecten doorgezet.'.format(n))

        details = context.layersToLoadOnCompletion()
        if dest_id in details:
            self._pp = _Styler(group_field, species_field, color_mode, seed)
            details[dest_id].setPostProcessor(self._pp)
            context.setLayersToLoadOnCompletion(details)
        else:
            feedback.pushWarning('Uitvoerlaag wordt niet geladen; symbologie niet toegepast.')

        return {self.OUTPUT: dest_id}
