r"""
NDFF: Jaarrond beschermde vogels binnen straal (Processing-tool).

Trekt uit een gecategoriseerde vogellaag (ow_cat-veld) een ontdubbelde lijst:
- alle soorten binnen een gekozen straal van het projectgebied
- alleen jaarrond beschermde categorieen (default 1,2,3,4)
- optioneel gefilterd op gedrag (overvliegers) en telonderwerp (dode dieren)

Output: CSV (soort;categorie) en kopieerbaar tekstblok in de log.
Vereist dat de vogellaag al gecategoriseerd is met "NDFF Vogels categoriseren".

Verschijnt onder Scripts > NDFF-analyse. Installeren: bestand in
  ...\QGIS3\profiles\default\processing\scripts\
en toolbox verversen.
"""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterDistance,
    QgsProcessingParameterString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFileDestination,
    QgsProcessingException,
    QgsGeometry,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsProject,
    NULL,
)


class JaarrondVogelsBinnenStraalalgorithm(QgsProcessingAlgorithm):

    BIRDS = 'BIRDS'
    PROJECT_AREA = 'PROJECT_AREA'
    RADIUS = 'RADIUS'
    JAARROND_CATS = 'JAARROND_CATS'
    EXCLUDE_DEAD = 'EXCLUDE_DEAD'
    EXCLUDE_FLYING = 'EXCLUDE_FLYING'
    OUTPUT = 'OUTPUT'

    # Vaste instellingen
    CATEGORY_FIELD = 'ow_cat'
    SPECIES_FIELD = 'soort_ned'
    BEHAVIOR_FIELD = 'gedrag'
    TELONDERWERP_FIELD = 'telondrwrp'

    def tr(self, s):
        return QCoreApplication.translate('Processing', s)

    def createInstance(self):
        return JaarrondVogelsBinnenStraalalgorithm()

    def name(self):
        return 'jaarrond_vogels_binnen_straal'

    def displayName(self):
        return self.tr('NDFF: Jaarrond beschermde vogels binnen straal')

    def group(self):
        return self.tr('NDFF-analyse')

    def groupId(self):
        return 'ndff_analyse'

    def shortHelpString(self):
        return self.tr(
            'Geeft een lijst van jaarrond beschermde vogels in een straal van het projectgebied. '
            'Output: CSV en plakbare tabel in het log. Filtert standaard dode dieren en overvliegers uit.'
            ''
            'Zorg eerst dat de laag is gecategoriseerd met "NDFF Vogels categoriseren"'
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.BIRDS, self.tr('Gecategoriseerde vogellaag (ow_cat-veld)')))

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.PROJECT_AREA, self.tr('Projectgebied (vlak)')))

        self.addParameter(QgsProcessingParameterDistance(
            self.RADIUS, self.tr('Straal rond projectgebied'),
            defaultValue=1000, parentParameterName=self.BIRDS))

        self.addParameter(QgsProcessingParameterString(
            self.JAARROND_CATS, self.tr('Jaarrond beschermde categorieen (kommagescheiden)'),
            defaultValue='1,2,3,4'))

        self.addParameter(QgsProcessingParameterBoolean(
            self.EXCLUDE_DEAD, self.tr('Negeer dode dieren'),
            defaultValue=True))

        self.addParameter(QgsProcessingParameterBoolean(
            self.EXCLUDE_FLYING, self.tr('Negeer overvliegende dieren'),
            defaultValue=True))

        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT, self.tr('Uitvoer-CSV'),
            fileFilter='CSV (*.csv)'))

    def processAlgorithm(self, parameters, context, feedback):
        birds = self.parameterAsVectorLayer(parameters, self.BIRDS, context)
        area = self.parameterAsVectorLayer(parameters, self.PROJECT_AREA, context)
        radius = self.parameterAsDouble(parameters, self.RADIUS, context)
        cats_raw = self.parameterAsString(parameters, self.JAARROND_CATS, context)
        exclude_dead = self.parameterAsBool(parameters, self.EXCLUDE_DEAD, context)
        exclude_flying = self.parameterAsBool(parameters, self.EXCLUDE_FLYING, context)
        csv_path = self.parameterAsFileOutput(parameters, self.OUTPUT, context)

        # Controleer of ow_cat-veld bestaat
        if birds.fields().indexFromName(self.CATEGORY_FIELD) == -1:
            raise QgsProcessingException(
                'Veld "{}" ontbreekt. Draai eerst "NDFF Vogels categoriseren" op deze laag.'.format(
                    self.CATEGORY_FIELD))

        jaarrond = {c.strip() for c in cats_raw.split(',') if c.strip()}
        if not jaarrond:
            raise QgsProcessingException('Geen categorieen opgegeven.')
        feedback.pushInfo('Jaarrond-categorieen: {}'.format(', '.join(sorted(jaarrond))))

        # Filters samenstellen
        filters = []
        if exclude_dead and birds.fields().indexFromName(self.TELONDERWERP_FIELD) != -1:
            filters.append((self.TELONDERWERP_FIELD, ['dood exemplaar']))
            feedback.pushInfo('Filter: sluit dode dieren uit ({})'.format(self.TELONDERWERP_FIELD))
        if exclude_flying and birds.fields().indexFromName(self.BEHAVIOR_FIELD) != -1:
            filters.append((self.BEHAVIOR_FIELD, ['overvliegend']))
            feedback.pushInfo('Filter: sluit overvliegers uit ({})'.format(self.BEHAVIOR_FIELD))

        if birds.crs().isGeographic():
            feedback.pushWarning(
                'Vogellaag-CRS is geografisch (graden); straal in meters klopt dan niet. '
                'Gebruik RD New (EPSG:28992).')

        # Projectgebied ophalen, transformeren, bufferen
        transform = None
        if area.crs() != birds.crs():
            transform = QgsCoordinateTransform(area.crs(), birds.crs(), QgsProject.instance())
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
        buffer = QgsGeometry.unaryUnion(geoms).buffer(radius, 24)

        # Verzamel jaarrond beschermde vogels within buffer
        req = QgsFeatureRequest().setFilterRect(buffer.boundingBox())
        seen = set()
        rows = []
        species_any = set()
        n_excluded = 0

        for feat in birds.getFeatures(req):
            g = feat.geometry()
            if g is None or g.isEmpty() or not buffer.intersects(g):
                continue
            
            # Check categorie
            cval = feat[self.CATEGORY_FIELD]
            cat = '' if cval is None or cval == NULL else str(cval).strip()
            if cat not in jaarrond:
                continue
            
            # Soort
            sval = feat[self.SPECIES_FIELD]
            soort = '' if sval is None or sval == NULL else str(sval).strip()
            species_any.add(soort)

            # Filters toepassen
            excluded = False
            for fname, terms in filters:
                val = feat[fname]
                text = '' if val is None or val == NULL else str(val).lower()
                if any(term in text for term in terms):
                    excluded = True
                    break
            if excluded:
                n_excluded += 1
                continue

            # Ontdubbelen op (soort, categorie)
            key = (soort, cat)
            if key in seen:
                continue
            seen.add(key)
            rows.append((soort, cat))

        rows.sort(key=lambda r: r[0].lower())
        dropped = sorted(species_any - {r[0] for r in rows}, key=str.lower)

        # CSV schrijven
        with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
            f.write('soort;categorie\n')
            for soort, cat in rows:
                f.write('{};{}\n'.format(soort, cat))

        # Output in log
        feedback.pushInfo('')
        feedback.pushInfo('--- Kopieerbaar (soort <tab> categorie) ---')
        feedback.pushInfo('Soort\tCategorie')
        for soort, cat in rows:
            feedback.pushInfo('{}\t{}'.format(soort, cat))
        feedback.pushInfo('--- einde ---')
        feedback.pushInfo('')
        feedback.pushInfo('{} jaarrond beschermde soorten binnen {:.0f} m.'.format(len(rows), radius))
        if filters:
            feedback.pushInfo('{} waarnemingen gefilterd (dood/overvliegend).'.format(n_excluded))
            if dropped:
                feedback.pushWarning('Soorten volledig weggefilterd: {}'.format(', '.join(dropped)))

        return {self.OUTPUT: csv_path}