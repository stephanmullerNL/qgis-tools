r"""
Vogels categoriseren + symboliseren (zwaartepunten) - Processing-tool.

Neemt een NDFF-vogellaag (locatievlakken), maakt er zwaartepunten van, kent per
waarnemer de provinciale beschermingscategorie toe uit de lookup-CSV, en zet er
symbologie op (categorie = groep, soort eronder). Levert een nieuwe puntlaag op.

Verschijnt onder Scripts > Ecologie. Installeren: bestand in
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
    QgsProcessingParameterField,
    QgsProcessingParameterEnum,
    QgsProcessingParameterString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterNumber,
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


class VogelsCategoriserenAlgorithm(QgsProcessingAlgorithm):

    INPUT = 'INPUT'
    CSV = 'CSV'
    PROVINCE = 'PROVINCE'
    SPECIES_FIELD = 'SPECIES_FIELD'
    OUTPUT_FIELD = 'OUTPUT_FIELD'
    DEFAULT_CAT = 'DEFAULT_CAT'
    CENTROIDS = 'CENTROIDS'
    SYMBOLIZE = 'SYMBOLIZE'
    COLOR_MODE = 'COLOR_MODE'
    SEED = 'SEED'
    OUTPUT = 'OUTPUT'

    PROVINCES = [
        'Landelijk', 'Drenthe', 'Flevoland', 'Friesland', 'Gelderland',
        'Groningen', 'Limburg', 'Noord-Brabant', 'Noord-Holland',
        'Overijssel', 'Utrecht', 'Zeeland', 'Zuid-Holland',
    ]
    COLOR_MODES = ['Willekeurig per soort', 'Eén kleur per categorie', 'Tint per soort binnen categorie']

    def tr(self, s):
        return QCoreApplication.translate('Processing', s)

    def createInstance(self):
        return VogelsCategoriserenAlgorithm()

    def name(self):
        return 'vogels_categoriseren'

    def displayName(self):
        return self.tr('NDFF vogels categoriseren + symboliseren')

    def group(self):
        return self.tr('Ecologie')

    def groupId(self):
        return 'ecologie'

    def shortHelpString(self):
        return self.tr(
            'Maakt zwaartepunten van een NDFF-vogellaag, kent de provinciale '
            'beschermingscategorie toe uit de lookup-CSV (veld ow_cat, default '
            '"overige"), en zet er symbologie op. Levert een nieuwe puntlaag op. '
            'Provincies zonder eigen blok vallen terug op Landelijk.'
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, self.tr('NDFF-vogellaag')))
        self.addParameter(QgsProcessingParameterFile(
            self.CSV, self.tr('Lookup-CSV (soort;provincie;categorie;peildatum)'),
            extension='csv',
            defaultValue=r'\\server\Mappen\Basis en uitleg QGIS\Toolbox\vogels_categorie_per_provincie.csv'))
        self.addParameter(QgsProcessingParameterEnum(
            self.PROVINCE, self.tr('Provincie van het project'),
            options=self.PROVINCES, defaultValue=0))
        self.addParameter(QgsProcessingParameterField(
            self.SPECIES_FIELD, self.tr('Soortveld'),
            parentLayerParameterName=self.INPUT, defaultValue='soort_ned'))
        self.addParameter(QgsProcessingParameterString(
            self.OUTPUT_FIELD, self.tr('Naam categorie-veld'), defaultValue='ow_cat'))
        self.addParameter(QgsProcessingParameterString(
            self.DEFAULT_CAT, self.tr('Default voor niet-gevonden soorten'), defaultValue='overige'))
        self.addParameter(QgsProcessingParameterBoolean(
            self.CENTROIDS, self.tr('Eerst zwaartepunten maken (invoer = NDFF-vlakken)'), defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.SYMBOLIZE, self.tr('Meteen symbologie toepassen'), defaultValue=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.COLOR_MODE, self.tr('Kleurmodus'), options=self.COLOR_MODES, defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.SEED, self.tr('Seed voor willekeur (-1 = elke keer anders)'),
            type=QgsProcessingParameterNumber.Integer, defaultValue=-1))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr('Zwaartepunten, gecategoriseerd')))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        csv_path = self.parameterAsFile(parameters, self.CSV, context)
        prov_idx = self.parameterAsEnum(parameters, self.PROVINCE, context)
        species_field = self.parameterAsString(parameters, self.SPECIES_FIELD, context)
        out_field = (self.parameterAsString(parameters, self.OUTPUT_FIELD, context).strip() or 'ow_cat')
        default_cat = (self.parameterAsString(parameters, self.DEFAULT_CAT, context).strip() or 'overige')
        make_centroids = self.parameterAsBool(parameters, self.CENTROIDS, context)
        symbolize = self.parameterAsBool(parameters, self.SYMBOLIZE, context)
        color_mode = self.parameterAsEnum(parameters, self.COLOR_MODE, context)
        seed = self.parameterAsInt(parameters, self.SEED, context)
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

        used_prov = chosen_prov if chosen_prov in blocks else 'Landelijk'
        if used_prov not in blocks:
            raise QgsProcessingException('Geen blok voor {} en geen Landelijk.'.format(chosen_prov))
        lookup = blocks[used_prov]
        if used_prov != chosen_prov:
            feedback.pushInfo('{} heeft geen eigen blok -> Landelijk gebruikt.'.format(chosen_prov))
        feedback.pushInfo('Provincieblok: {} ({} soorten).'.format(used_prov, len(lookup)))

        # Uitvoervelden = invoervelden + categorie-veld
        out_fields = QgsFields(source.fields())
        idx = out_fields.indexOf(out_field)
        if idx == -1:
            out_fields.append(QgsField(out_field, QVariant.String))
            idx = out_fields.indexOf(out_field)

        out_wkb = QgsWkbTypes.Point if make_centroids else source.wkbType()
        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, out_fields, out_wkb, source.sourceCrs())

        n_match = n_default = 0
        for feat in source.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            if make_centroids:
                geom = geom.centroid()

            sval = feat[species_field]
            key = '' if sval is None or sval == NULL else str(sval).strip().lower()
            if key and key in lookup:
                cat = lookup[key]; n_match += 1
            else:
                cat = default_cat; n_default += 1

            attrs = list(feat.attributes())
            if len(attrs) < len(out_fields):
                attrs += [None] * (len(out_fields) - len(attrs))
            attrs[idx] = cat

            nf = QgsFeature(out_fields)
            nf.setAttributes(attrs)
            nf.setGeometry(geom)
            sink.addFeature(nf)

        feedback.pushInfo('Gecategoriseerd: {} met categorie, {} als "{}".'.format(
            n_match, n_default, default_cat))

        details = context.layersToLoadOnCompletion()
        if symbolize and dest_id in details:
            self._pp = _Styler(out_field, species_field, color_mode, seed)
            details[dest_id].setPostProcessor(self._pp)
            context.setLayersToLoadOnCompletion(details)

        return {self.OUTPUT: dest_id}
