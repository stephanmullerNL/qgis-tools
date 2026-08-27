"""
NDFF soorten in/rond projectgebied (Processing-tool).

Geeft een ontdubbelde lijst van alle soorten waargenomen:
- IN het projectgebied
- IN een buffer rond het projectgebied (default 2 km)

Per soort de dichtste waarneming (afstand) en de waarnemingsdatum.
Output: tekstblok in de log, tab-gescheiden (plakbaar in Excel).

Werkt op een NDFF puntenlaag met velden soort_ned (soortnaam) en datm_start (datum).

Verschijnt in de Verwerkingstoolbox onder Scripts > NDFF.
Installeren: zet dit bestand in
  ...\QGIS3\profiles\default\processing\scripts\
en ververs de toolbox.
"""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterDistance,
    QgsProcessingParameterEnum,
    QgsProcessingException,
    QgsGeometry,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsProject,
)


class NdffSoortenInProjectgebiedAlgorithm(QgsProcessingAlgorithm):

    NDFF = 'NDFF'
    PROJECT_AREA = 'PROJECT_AREA'
    BUFFER_DIST = 'BUFFER_DIST'
    CATEGORY_FIELD = 'CATEGORY_FIELD'
    SORT_BY = 'SORT_BY'
    
    CATEGORY_OPTIONS = ['Vogels (ow_cat)', 'Niet-vogels (srtgroepen)']
    CATEGORY_FIELDS = {'Vogels (ow_cat)': 'ow_cat', 'Niet-vogels (srtgroepen)': 'srtgroepen'}

    def tr(self, s):
        return QCoreApplication.translate('Processing', s)

    def createInstance(self):
        return NdffSoortenInProjectgebiedAlgorithm()

    def name(self):
        return 'ndff_soorten_in_projectgebied'

    def displayName(self):
        return self.tr('NDFF: Soorten in/rond projectgebied')

    def group(self):
        return self.tr('NDFF-analyse')

    def groupId(self):
        return 'ndff_analyse'

    def shortHelpString(self):
        return self.tr(
            'Geeft per soort de dichtste waarneming in het projectgebied en buffer, '
            'gegroepeerd per categorie (vogels of niet-vogels). '
            'Output: plakbare tabel in het log.'
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.NDFF, self.tr('NDFF puntenlaag (soort_ned, datm_start)'),
            types=[QgsProcessing.TypeVectorPoint]))

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.PROJECT_AREA, self.tr('Projectgebied (polygon)'),
            types=[QgsProcessing.TypeVectorPolygon]))

        self.addParameter(QgsProcessingParameterDistance(
            self.BUFFER_DIST, self.tr('Buffer rond projectgebied'),
            defaultValue=2000, minValue=0, parentParameterName=self.PROJECT_AREA))
        
        self.addParameter(QgsProcessingParameterEnum(
            self.CATEGORY_FIELD, self.tr('Groepering'),
            options=self.CATEGORY_OPTIONS, defaultValue=0))
        
        self.addParameter(QgsProcessingParameterEnum(
            self.SORT_BY, self.tr('Sorteren op'),
            options=[self.tr('Soortnaam (A-Z)'), self.tr('Afstand (dichtste eerst)')],
            defaultValue=0))

    def processAlgorithm(self, parameters, context, feedback):
        ndff = self.parameterAsVectorLayer(parameters, self.NDFF, context)
        area = self.parameterAsVectorLayer(parameters, self.PROJECT_AREA, context)
        buffer_dist = self.parameterAsDouble(parameters, self.BUFFER_DIST, context)
        category_choice = self.parameterAsEnum(parameters, self.CATEGORY_FIELD, context)
        sort_by = self.parameterAsInt(parameters, self.SORT_BY, context)  # 0=naam, 1=afstand
        
        # Zet enum-keuze om naar veldnaam
        category_choice_label = self.CATEGORY_OPTIONS[category_choice]
        category_field = self.CATEGORY_FIELDS[category_choice_label]
        
        # Controleer of categorie-veld bestaat
        use_categories = False
        if category_field and ndff.fields().indexFromName(category_field) != -1:
            use_categories = True

        # Controleer noodzakelijke velden
        if ndff.fields().indexFromName('soort_ned') == -1:
            raise QgsProcessingException('Veld "soort_ned" ontbreekt in NDFF-laag.')
        if ndff.fields().indexFromName('datm_start') == -1:
            raise QgsProcessingException('Veld "datm_start" ontbreekt in NDFF-laag.')

        # Projectgebied ophalen, transformeren indien nodig, en bufferen
        transform = None
        if area.crs() != ndff.crs():
            transform = QgsCoordinateTransform(area.crs(), ndff.crs(), QgsProject.instance())
        
        geoms = []
        for f in area.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            if transform is not None:
                g = QgsGeometry(g)
                g.transform(transform)
            geoms.append(g)
        
        if not geoms:
            raise QgsProcessingException('Het projectgebied heeft geen geometrie.')
        
        project_geom = QgsGeometry.unaryUnion(geoms)
        buffer_geom = project_geom.buffer(buffer_dist, 24)

        # Verzamel per soort de dichtste waarneming
        # Structuur: {categorie: {soort: {afstand, datum}}}
        in_gebied = {}
        in_buffer = {}

        req = QgsFeatureRequest().setFilterRect(buffer_geom.boundingBox())
        
        for feature in ndff.getFeatures(req):
            geom = feature.geometry()
            if geom is None or geom.isEmpty():
                continue
            
            # Controleer of punt in de buffer ligt
            if not buffer_geom.intersects(geom):
                continue
            
            soort = feature['soort_ned']
            datum = feature['datm_start']
            category = feature[category_field] if use_categories else 'Alle soorten'
            distance = project_geom.distance(geom)
            
            if project_geom.contains(geom):
                # IN het gebied
                if category not in in_gebied:
                    in_gebied[category] = {}
                if soort not in in_gebied[category] or distance < in_gebied[category][soort]['afstand']:
                    in_gebied[category][soort] = {'afstand': distance, 'datum': datum}
            elif buffer_geom.contains(geom):
                # IN buffer, BUITEN gebied
                if category not in in_buffer:
                    in_buffer[category] = {}
                if soort not in in_buffer[category] or distance < in_buffer[category][soort]['afstand']:
                    in_buffer[category][soort] = {'afstand': distance, 'datum': datum}

        # Output in log
        feedback.pushInfo('')
        feedback.pushInfo('='*70)
        feedback.pushInfo('NDFF SOORTEN ANALYSE')
        feedback.pushInfo('='*70)

        # Helper: datum netjes formatteren met haakjes
        def format_datum(d):
            if d is None:
                return '(onbekend)'
            if hasattr(d, 'toString'):  # QDate/QDateTime object
                return '(' + d.toString('yyyy-MM-dd') + ')'
            return '(' + str(d) + ')'
        
        # Sorteer-functie per categorie
        def sort_species(category_dict, sort_by):
            items = []
            for soort, data in category_dict.items():
                items.append((soort, data, data['afstand']))
            
            if sort_by == 1:  # Op afstand
                items.sort(key=lambda x: (x[2], x[0].lower()))
            else:  # Default: op naam
                items.sort(key=lambda x: (x[0].lower(), x[2]))
            return items
        
        # Tota aantal soorten tellen
        total_gebied = sum(len(cat) for cat in in_gebied.values())
        total_buffer = sum(len(cat) for cat in in_buffer.values())
        
        # IN GEBIED
        feedback.pushInfo('')
        feedback.pushInfo('📍 IN PROJECTGEBIED ({} soorten):'.format(total_gebied))
        feedback.pushInfo('-'*70)
        
        if in_gebied:
            for category in sorted(in_gebied.keys()):
                feedback.pushInfo('')
                feedback.pushInfo(category)
                feedback.pushInfo('Soort\tAfstand (m)\tDatum')
                
                species_list = sort_species(in_gebied[category], sort_by)
                for soort, data, _ in species_list:
                    afst = data['afstand']
                    datum = format_datum(data['datum'])
                    feedback.pushInfo('{}\t{:.0f}\t{}'.format(soort, afst, datum))
        else:
            feedback.pushInfo('(geen waarnemingen)')

        # IN BUFFER
        feedback.pushInfo('')
        feedback.pushInfo('📍 IN BUFFER {:.0f}M RONDOM ({} soorten):'.format(buffer_dist, total_buffer))
        feedback.pushInfo('-'*70)
        
        if in_buffer:
            for category in sorted(in_buffer.keys()):
                feedback.pushInfo('')
                feedback.pushInfo(category)
                feedback.pushInfo('Soort\tAfstand (m)\tDatum')
                
                species_list = sort_species(in_buffer[category], sort_by)
                for soort, data, _ in species_list:
                    afst = data['afstand']
                    datum = format_datum(data['datum'])
                    feedback.pushInfo('{}\t{:.0f}\t{}'.format(soort, afst, datum))
        else:
            feedback.pushInfo('(geen waarnemingen)')

        feedback.pushInfo('')
        feedback.pushInfo('='*70)
        feedback.pushInfo('Totaal: {} soorten aangetroffen'.format(len(in_gebied) + len(in_buffer)))
        feedback.pushInfo('='*70)
        feedback.pushInfo('')

        return {}