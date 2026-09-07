# React 19- og MUI 9-gennemgang – PlanIQ Display

## Implementeret runtime

Frontendens gratis, produktionsrelevante UI-stack er opgraderet og låst til:

- React og ReactDOM `19.2.7`
- Material UI og Material Icons `9.2.0`
- MUI X Date Pickers Community `9.9.0`
- Emotion React `11.14.0` og Emotion Styled `11.14.1`
- date-fns `4.4.0`
- `@hello-pangea/dnd` `18.0.1`
- React Hooks ESLint-plugin `7.1.1`

Den udfasede `react-beautiful-dnd` er fjernet. `@hello-pangea/dnd` bevarer den komponentbaserede drag-and-drop-kontrakt, som ClientInfo-siden allerede bruger.

## Gennemførte MUI 9-migrationer

- Gamle Grid breakpoint-props er migreret til `size`.
- Udfasede TextField-, Dialog-, Drawer-, Menu- og ListItemText-props er migreret til `slotProps`.
- Fjernede direkte MUI system-props er flyttet til `sx`.
- Fjernede Material Icons-navne er erstattet med understøttede `Outlined`-navne.
- Date Pickers bruger MUI X 9 og date-fns 4-adapteren.
- Alle `MenuItem`-placeringer er kontrolleret mod MUI 9's kontekstkrav.
- Production-builden bruger kontrollerede vendor-chunks, så det eksisterende bundlebudget bevares.

## UI-moderniseringer

- Login-, password-, session-, audit-, installationskode-, organisations- og kalenderhandlinger bruger MUI-knappens indbyggede `loading`-tilstand.
- Brugeradministrationens sorterbare tabeloverskrifter bruger `TableSortLabel` med korrekt `sortDirection`.
- Alle midlertidige procesbeskeder bruger den fælles `AppSnackbar`.
- Alle lokale snackbar-instans­er samles i én fælles `AppSnackbarProvider`, så transparente snackbar-lag aldrig overlapper og fremstår mere uigennemsigtige end aftalt.
- Display-snackbarens eksisterende layout er bevaret: nederst i midten, `filled`, mørkt Display-udtryk og præcis 80 % baggrundsopacitet.

## Bevidst bevaret

Følgende er gennemgået, men ikke redesignet, fordi det ville ændre produktadfærd eller kræve et særskilt UX-step:

- Remote Desktop-filmanagerens specialiserede kontekstmenuer og flertrinsoperationer.
- HLS/livestream-kontroller og deres statusindikatorer.
- Kalenderens tabeller, printlayout og dagsspecifikke redigeringsflow.
- ClientFlow-version-, rollback- og installationskontrakter.
- Klikbare tabelrækker, hvor hele rækken fortsat er den definerede valgoverflade.
- MUI X Pro-komponenter; der er ikke tilføjet betalingsafhængigheder.

## CI-kontrakter

CI kontrollerer nu:

- de præcise React-, MUI-, MUI X-, date-fns- og drag-and-drop-versioner
- at `react-beautiful-dnd` ikke genindføres
- rendering af `MenuItem` under `MenuList`
- MUI 9 Grid, TextField slots og Button loading
- MUI X Date Pickers 9 med date-fns 4
- den fælles snackbarplacering, varighed, transparens, single-host-kontrakt og click-away-adfærd
## Snackbar-audit i hele Display-repoet

Den fælles snackbar-kontrakt er efterfølgende udvidet til alle midlertidige,
dismissible procesbeskeder i Remote Desktop, filhåndtering, organisationshandlinger
og audit-oprydning. Disse beskeder bruger nu den globale `AppSnackbarProvider` og
præcis `SNACKBAR_BACKGROUND_OPACITY = 0.8`.

Vedvarende beskeder, der hører til dokumentflowet, er bevidst fortsat inline
`Alert`: formularvalidering, rettighedsbeskeder, bekræftelsesdialoger, sæsonberedskab,
stream-/opdateringsstatus og andre oplysninger, som ikke må forsvinde automatisk.
Filmanagerens udvalgsværktøj er ændret fra `Alert` til en semantisk `Paper`-toolbar,
så den ikke visuelt kan forveksles med en snackbar.

