r"""
Jaarrond beschermde vogels binnen straal (Processing-tool).

Trekt uit een reeds gecategoriseerde vogellaag een ontdubbelde uitdraai:
- alle soorten binnen een gekozen straal (bv. 1000 of 2000 m) van het projectgebied
- alleen de categorieen die jaarrond beschermd zijn (default 1,2,3,4)
- output: een CSV (soort;categorie) en een kopieerbaar tekstblok in de log

Vereist dat de vogellaag al een categorie-veld heeft (bv. ow_cat), aangemaakt met
de tool 'Vogels categoriseren + symboliseren'.

Verschijnt in de Verwerkingstoolbox onder Scripts > Ecologie.
Installeren: zet dit bestand in
  ...\QGIS3\profiles\default\processing\scripts\
en ververs de toolbox.
"""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterField,
    QgsProcessingParameterDistance,
    QgsProcessingParameterString,
    QgsProcessingParameterFileDestination,
    QgsProcessingException,
    QgsGeometry,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsProject,
    NULL,
)


class JaarrondVogelsBinnenStraalAlgorithm(QgsProcessingAlgorithm):

    BIRDS = 'BIRDS'
    PROJECT_AREA = 'PROJECT_AREA'
    CATEGORY_FIELD = 'CATEGORY_FIELD'
    SPECIES_FIELD = 'SPECIES_FIELD'
    RADIUS = 'RADIUS'
    JAARROND_CATS = 'JAARROND_CATS'
    BEHAVIOR_FIELD = 'BEHAVIOR_FIELD'
    EXCLUDE_TERMS = 'EXCLUDE_TERMS'
    TELONDERWERP_FIELD = 'TELONDERWERP_FIELD'
    TELONDERWERP_TERMS = 'TELONDERWERP_TERMS'
    OUTPUT = 'OUTPUT'

    def tr(self, s):
        return QCoreApplication.translate('Processing', s)

    def createInstance(self):
        return JaarrondVogelsBinnenStraalAlgorithm()

    def name(self):
        return 'jaarrond_vogels_binnen_straal'

    def displayName(self):
        return self.tr('Jaarrond beschermde vogels binnen straal')

    def group(self):
        return self.tr('Ecologie')

    def groupId(self):
        return 'ecologie'

    def shortHelpString(self):
        return self.tr(
            'Maakt een CSV van jaarrond beschermde vogelsoorten binnen een gekozen '
            'straal van het projectgebied, plus een kopieerbaar tekstblok in de log. '
            'Werkt op een laag die al een categorie-veld heeft (bv. ow_cat). Kies de '
            'straal (1000 m = 1 km, 2000 m bij zware werkzaamheden) en welke '
            'categorieen jaarrond beschermd zijn. Let op: dat verschilt per provincie '
            '-- Landelijk/Drenthe/Friesland 1,2,3,4; Flevoland 1,2,3,4,5a; '
            'Gelderland/Overijssel alleen 1; Limburg 1. Filtert standaard '
            'overvliegers (gedrag) en dode exemplaren (telonderwerp) weg; beide '
            'instelbaar of leeg te laten.'
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.BIRDS, self.tr('Gecategoriseerde vogellaag')))

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.PROJECT_AREA, self.tr('Projectgebied (vlak)')))

        self.addParameter(QgsProcessingParameterField(
            self.CATEGORY_FIELD, self.tr('Categorie-veld'),
            parentLayerParameterName=self.BIRDS, defaultValue='ow_cat'))

        self.addParameter(QgsProcessingParameterField(
            self.SPECIES_FIELD, self.tr('Soortveld'),
            parentLayerParameterName=self.BIRDS, defaultValue='soort_ned'))

        self.addParameter(QgsProcessingParameterDistance(
            self.RADIUS, self.tr('Straal rond projectgebied'),
            defaultValue=1000, parentParameterName=self.BIRDS))

        self.addParameter(QgsProcessingParameterString(
            self.JAARROND_CATS, self.tr('Jaarrond beschermde categorieen (kommagescheiden)'),
            defaultValue='1,2,3,4'))

        self.addParameter(QgsProcessingParameterField(
            self.BEHAVIOR_FIELD, self.tr('Gedrag-veld'),
            parentLayerParameterName=self.BIRDS, defaultValue='gedrag', optional=True))

        self.addParameter(QgsProcessingParameterString(
            self.EXCLUDE_TERMS, self.tr('Uit te sluiten gedrag-termen (kommagescheiden)'),
            defaultValue='overvliegend'))

        self.addParameter(QgsProcessingParameterField(
            self.TELONDERWERP_FIELD, self.tr('Telonderwerp-veld'),
            parentLayerParameterName=self.BIRDS, defaultValue='telonderwrp', optional=True))

        self.addParameter(QgsProcessingParameterString(
            self.TELONDERWERP_TERMS, self.tr('Uit te sluiten telonderwerp-termen (kommagescheiden)'),
            defaultValue='dood exemplaar'))

        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT, self.tr('Uitvoer-CSV'),
            fileFilter='CSV (*.csv)'))

    def processAlgorithm(self, parameters, context, feedback):
        birds = self.parameterAsVectorLayer(parameters, self.BIRDS, context)
        area = self.parameterAsVectorLayer(parameters, self.PROJECT_AREA, context)
        cat_field = self.parameterAsString(parameters, self.CATEGORY_FIELD, context)
        species_field = self.parameterAsString(parameters, self.SPECIES_FIELD, context)
        radius = self.parameterAsDouble(parameters, self.RADIUS, context)
        cats_raw = self.parameterAsString(parameters, self.JAARROND_CATS, context)
        behavior_field = self.parameterAsString(parameters, self.BEHAVIOR_FIELD, context)
        exclude_raw = self.parameterAsString(parameters, self.EXCLUDE_TERMS, context)
        telonderwerp_field = self.parameterAsString(parameters, self.TELONDERWERP_FIELD, context)
        telonderwerp_raw = self.parameterAsString(parameters, self.TELONDERWERP_TERMS, context)
        csv_path = self.parameterAsFileOutput(parameters, self.OUTPUT, context)

        if birds.fields().indexFromName(cat_field) == -1:
            raise QgsProcessingException(
                'Veld "{}" ontbreekt. Draai eerst "Vogels categoriseren + symboliseren".'.format(cat_field))

        jaarrond = {c.strip() for c in cats_raw.split(',') if c.strip()}
        if not jaarrond:
            raise QgsProcessingException('Geen categorieen opgegeven.')
        feedback.pushInfo('Jaarrond-categorieen: {}'.format(', '.join(sorted(jaarrond))))

        # Bouw de weglaat-filters op: (veldnaam, [termen]). Ontbreekt het veld, dan waarschuwen en overslaan.
        def build_filter(field_name, raw, label):
            if not field_name:
                return None
            terms = [t.strip().lower() for t in raw.split(',') if t.strip()]
            if not terms:
                return None
            if birds.fields().indexFromName(field_name) == -1:
                feedback.pushWarning('{}-veld "{}" niet gevonden; dit filter wordt overgeslagen.'.format(
                    label, field_name))
                return None
            feedback.pushInfo('{}-filter op "{}": sluit uit wat bevat: {}'.format(
                label, field_name, ', '.join(terms)))
            return (field_name, terms)

        filters = [f for f in (
            build_filter(behavior_field, exclude_raw, 'Gedrag'),
            build_filter(telonderwerp_field, telonderwerp_raw, 'Telonderwerp'),
        ) if f is not None]

        if birds.crs().isGeographic():
            feedback.pushWarning(
                'Vogellaag-CRS is geografisch (graden); een straal in meters klopt dan niet. '
                'Gebruik een metrisch CRS zoals RD New (EPSG:28992).')

        # Projectgebied verzamelen, indien nodig transformeren naar CRS van de vogels, en bufferen
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

        # Vogels binnen de buffer, in een jaarrond-categorie, ontdubbeld op (soort, categorie)
        req = QgsFeatureRequest().setFilterRect(buffer.boundingBox())
        seen = set()
        rows = []
        species_any = set()   # soorten met een jaarrond-waarneming binnen de straal (voor het filter)
        n_excluded = 0
        for feat in birds.getFeatures(req):
            g = feat.geometry()
            if g is None or g.isEmpty() or not buffer.intersects(g):
                continue
            cval = feat[cat_field]
            cat = '' if cval is None or cval == NULL else str(cval).strip()
            if cat not in jaarrond:
                continue
            sval = feat[species_field]
            soort = '' if sval is None or sval == NULL else str(sval).strip()
            species_any.add(soort)

            # Weglaat-filters (gedrag = overvliegend, telonderwerp = dood exemplaar, ...)
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

            key = (soort, cat)
            if key in seen:
                continue
            seen.add(key)
            rows.append((soort, cat))

        rows.sort(key=lambda r: r[0].lower())

        # Soorten die volledig wegvielen doordat al hun waarnemingen overvliegers waren
        dropped = sorted(species_any - {r[0] for r in rows}, key=str.lower)

        # CSV wegschrijven (puntkomma, met BOM zodat Excel-NL het goed opent)
        with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
            f.write('soort;categorie\n')
            for soort, cat in rows:
                f.write('{};{}\n'.format(soort, cat))

        # Kopieerbaar blok in de log (tab-gescheiden -> plakt als kolommen in Word/Excel)
        feedback.pushInfo('')
        feedback.pushInfo('--- Kopieerbaar (soort <tab> categorie) ---')
        feedback.pushInfo('Soort\tCategorie')
        for soort, cat in rows:
            feedback.pushInfo('{}\t{}'.format(soort, cat))
        feedback.pushInfo('--- einde ---')
        feedback.pushInfo('')
        feedback.pushInfo('{} jaarrond beschermde soorten binnen {:.0f} m.'.format(len(rows), radius))
        if filters:
            feedback.pushInfo('{} waarnemingen weggefilterd (gedrag/telonderwerp).'.format(n_excluded))
            if dropped:
                feedback.pushWarning(
                    'Soorten volledig weggevallen door de filters (even controleren): {}'.format(
                        ', '.join(dropped)))

        return {self.OUTPUT: csv_path}
