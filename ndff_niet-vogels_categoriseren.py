r"""
NDFF: Niet-vogels categoriseren - Processing-tool (vereenvoudigd).

Neemt een NDFF-laag (niet-vogels: amfibieën, zoogdieren, enz.), maakt er 
zwaartepunten van en zet daar regelgebaseerde symbologie op: per soortgroep 
een ouderregel, met daaronder de soorten die voorkomen.

Versimpelde interface: selecteer input en output. Vaste instellingen: srtgroepen,
soort_ned, willekeurige kleuren, seed=-1.

Verschijnt onder Scripts > NDFF-analyse. Installeren: bestand in
  ...\QGIS3\profiles\default\processing\scripts\
en toolbox verversen.
"""

import random

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsProcessingLayerPostProcessorInterface,
    QgsFeature,
    QgsWkbTypes,
    QgsRuleBasedRenderer,
    QgsSymbol,
    QgsProject,
    NULL,
)


def _build_symbology(layer, group_field, species_field, seed):
    """Bouw symbologie op basis van soortgroepen."""
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
            sym.setColor(random_color())
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
    """Pas symbologie toe na laag laden."""
    def __init__(self, group_field, species_field, seed):
        super().__init__()
        self.group_field = group_field
        self.species_field = species_field
        self.seed = seed

    def postProcessLayer(self, layer, context, feedback):
        try:
            layer.setName('NDFF Niet-vogels (gecategoriseerd)')
            _build_symbology(layer, self.group_field, self.species_field, self.seed)
        except Exception as e:
            feedback.pushWarning('Symbologie mislukt: {}'.format(e))


class NdffNietVogelsCategoriserenAlgorithm(QgsProcessingAlgorithm):

    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'

    # Vaste instellingen
    GROUP_FIELD = 'srtgroepen'
    SPECIES_FIELD = 'soort_ned'
    SEED = -1

    def tr(self, s):
        return QCoreApplication.translate('Processing', s)

    def createInstance(self):
        return NdffNietVogelsCategoriserenAlgorithm()

    def name(self):
        return 'ndff_niet_vogels_categoriseren'

    def displayName(self):
        return self.tr('NDFF: Niet-vogels categoriseren')

    def group(self):
        return self.tr('NDFF-analyse')

    def groupId(self):
        return 'ndff_analyse'

    def shortHelpString(self):
        return self.tr(
            'Maakt zwaartepunten van een NDFF-laag (niet-vogels) en zet er '
            'regelgebaseerde symbologie op: per soortgroep een groep, met de '
            'soorten eronder. Levert een laag "NDFF Niet-vogels (zwaartepunten)" op.'
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, self.tr('NDFF-laag (vlakken)')))
        
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr('Laag opslaan als')))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)

        # Zwaartepunten altijd
        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context,
            source.fields(), QgsWkbTypes.Point, source.sourceCrs())

        n = 0
        for feat in source.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            
            # Maak zwaartepunt
            geom = geom.centroid()
            
            nf = QgsFeature(source.fields())
            nf.setAttributes(feat.attributes())
            nf.setGeometry(geom)
            sink.addFeature(nf)
            n += 1
        
        feedback.pushInfo('{} zwaartepunten weggeschreven.'.format(n))

        # Pas symbologie toe via postProcessor
        details = context.layersToLoadOnCompletion()
        if dest_id in details:
            self._pp = _Styler(self.GROUP_FIELD, self.SPECIES_FIELD, self.SEED)
            details[dest_id].setPostProcessor(self._pp)
            context.setLayersToLoadOnCompletion(details)
        else:
            feedback.pushWarning('Uitvoerlaag wordt niet geladen; symbologie niet toegepast.')

        return {self.OUTPUT: dest_id}