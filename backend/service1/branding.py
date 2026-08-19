"""Central produkt- og mail-identitet for PlanIQ Display.

Fase 1 bruger identiteten til API-titel/root. Fase 2 kan genbruge samme
konstanter i mail-skabeloner til reset-links og midlertidige adgangskoder.
"""

import os

PRODUCT_NAME = os.getenv("PRODUCT_NAME", "PlanIQ Display").strip() or "PlanIQ Display"
PRODUCT_SHORT_NAME = os.getenv("PRODUCT_SHORT_NAME", "Display").strip() or "Display"
PRODUCT_DOMAIN = os.getenv("PRODUCT_DOMAIN", "display.planiq.dk").strip() or "display.planiq.dk"

MAIL_FROM_NAME = os.getenv("MAIL_FROM_NAME", PRODUCT_NAME).strip() or PRODUCT_NAME
MAIL_PRODUCT_NAME = os.getenv("MAIL_PRODUCT_NAME", PRODUCT_NAME).strip() or PRODUCT_NAME
MAIL_LOGO_URL = (
    os.getenv("MAIL_LOGO_URL")
    or f"https://{PRODUCT_DOMAIN}/brand/planiq-display/planiq-display-logo.png"
).strip() or f"https://{PRODUCT_DOMAIN}/brand/planiq-display/planiq-display-logo.png"
