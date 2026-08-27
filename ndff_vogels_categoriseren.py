r"""
Vogels categoriseren + symboliseren - Processing-tool (vereenvoudigd).

Neemt een NDFF-vogellaag (locatievlakken), maakt er zwaartepunten van, kent de 
provinciale beschermingscategorie toe uit de lookup-CSV, en zet er symbologie op.
Levert een nieuwe puntlaag "NDFF Vogels (gecategoriseerd)" op.

Versimpelde interface: kies alleen provincie en waar op te slaan.
Vaste instellingen: soort_ned, ow_cat, willekeurige kleuren, seed=-1.

Verschijnt onder Scripts > NDFF-analyse. Installeren: bestand in
  ...\QGIS3\profiles\default\processing\scripts\
en toolbox verversen.
"""

import csv
import random

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFile,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingException,
    QgsProcessingLayerPostProcessorInterface,
    QgsFields,
    QgsField,
    QgsFeature,
    QgsWkbTypes,
    QgsRuleBasedRenderer,
    QgsSymbol,
    QgsProject,
    NULL,
)


def _build_symbology(layer, group_field, species_field, seed):
    """Bouw symbologie op basis van categorieën (groep) en soorten."""
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
            layer.setName('NDFF Vogels (gecategoriseerd)')
            _build_symbology(layer, self.group_field, self.species_field, self.seed)
        except Exception as e:
            feedback.pushWarning('Symbologie mislukt: {}'.format(e))


class VogelsCategoriserenAlgorithm(QgsProcessingAlgorithm):

    INPUT = 'INPUT'
    CSV = 'CSV'
    PROVINCE = 'PROVINCE'
    OUTPUT = 'OUTPUT'

    PROVINCES = [
        'Landelijk', 'Drenthe', 'Flevoland', 'Friesland', 'Gelderland',
        'Groningen', 'Limburg', 'Noord-Brabant', 'Noord-Holland',
        'Overijssel', 'Utrecht', 'Zeeland', 'Zuid-Holland',
    ]

    # Vaste instellingen
    SPECIES_FIELD = 'soort_ned'
    OUTPUT_FIELD = 'ow_cat'
    DEFAULT_CAT = 'overige'
    SEED = -1

    def tr(self, s):
        return QCoreApplication.translate('Processing', s)

    def createInstance(self):
        return VogelsCategoriserenAlgorithm()

    def name(self):
        return 'vogels_categoriseren'

    def displayName(self):
        return self.tr('NDFF vogels categoriseren + symboliseren')

    def group(self):
        return self.tr('NDFF-analyse')

    def groupId(self):
        return 'ndff_analyse'

    def shortHelpString(self):
        return self.tr(
            'Maakt zwaartepunten van een NDFF-vogellaag, kent de provinciale '
            'beschermingscategorie toe uit de lookup-CSV, en zet er symbologie op. '
            'Levert een laag "NDFF Vogels (gecategoriseerd)" op. '
            'Provincies zonder eigen blok vallen terug op Landelijk.'
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, self.tr('NDFF-vogellaag (vlakken)')))
        
        self.addParameter(QgsProcessingParameterFile(
            self.CSV, self.tr('Lookup-CSV (soort;provincie;categorie)'),
            extension='csv',
            defaultValue=r'\\server\Mappen\Basis en uitleg QGIS\Toolbox\vogels_categorie_per_provincie.csv'))
        
        self.addParameter(QgsProcessingParameterEnum(
            self.PROVINCE, self.tr('Provincie van het project'),
            options=self.PROVINCES, defaultValue=0))
        
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr('Laag opslaan als')))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        csv_path = self.parameterAsFile(parameters, self.CSV, context)
        prov_idx = self.parameterAsEnum(parameters, self.PROVINCE, context)
        chosen_prov = self.PROVINCES[prov_idx]

        # CSV inlezen
        blocks = {}
        try:
            with open(csv_path, encoding='utf-8-sig', newline='') as f:
                reader = csv.reader(f, delimiter=';')
                next(reader, None)
                for parts in reader:
                    if len(parts) < 3 or not parts[0].strip():
                        continue
                    soort, prov, cat = parts[0], parts[1], parts[2]
                    blocks.setdefault(prov.strip(), {})[soort.strip().lower()] = cat.strip()
        except Exception as e:
            raise QgsProcessingException('Kon de CSV niet lezen: {}'.format(e))
        if not blocks:
            raise QgsProcessingException('Geen bruikbare regels in de CSV.')

        # Juiste provincieblok kiezen (fallback op Landelijk)
        used_prov = chosen_prov if chosen_prov in blocks else 'Landelijk'
        if used_prov not in blocks:
            raise QgsProcessingException('Geen blok voor {} en geen Landelijk.'.format(chosen_prov))
        lookup = blocks[used_prov]
        if used_prov != chosen_prov:
            feedback.pushInfo('{} heeft geen eigen blok → Landelijk gebruikt.'.format(chosen_prov))
        feedback.pushInfo('Provincieblok: {} ({} soorten).'.format(used_prov, len(lookup)))

        # Uitvoervelden = invoervelden + ow_cat
        out_fields = QgsFields(source.fields())
        idx = out_fields.indexOf(self.OUTPUT_FIELD)
        if idx == -1:
            out_fields.append(QgsField(self.OUTPUT_FIELD, QVariant.String))
            idx = out_fields.indexOf(self.OUTPUT_FIELD)

        # Output altijd punten (zwaartepunten van vlakken)
        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, out_fields, QgsWkbTypes.Point, source.sourceCrs())

        n_match = n_default = 0
        for feat in source.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            
            # Maak zwaartepunt
            geom = geom.centroid()

            # Zoek soort op in lookup
            sval = feat[self.SPECIES_FIELD]
            key = '' if sval is None or sval == NULL else str(sval).strip().lower()
            if key and key in lookup:
                cat = lookup[key]
                n_match += 1
            else:
                cat = self.DEFAULT_CAT
                n_default += 1

            # Bouw output feature
            attrs = list(feat.attributes())
            if len(attrs) < len(out_fields):
                attrs += [None] * (len(out_fields) - len(attrs))
            attrs[idx] = cat

            nf = QgsFeature(out_fields)
            nf.setAttributes(attrs)
            nf.setGeometry(geom)
            sink.addFeature(nf)

        feedback.pushInfo('Gecategoriseerd: {} met categorie, {} als "{}".'.format(
            n_match, n_default, self.DEFAULT_CAT))

        # Pas symbologie toe via postProcessor
        details = context.layersToLoadOnCompletion()
        if dest_id in details:
            self._pp = _Styler(self.OUTPUT_FIELD, self.SPECIES_FIELD, self.SEED)
            details[dest_id].setPostProcessor(self._pp)
            context.setLayersToLoadOnCompletion(details)

        return {self.OUTPUT: dest_id}