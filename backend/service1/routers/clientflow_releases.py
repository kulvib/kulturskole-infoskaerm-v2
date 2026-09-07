from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_superadmin_user
from ..clientflow_releases import ClientFlowCatalogError, public_catalog

router = APIRouter(tags=["clientflow-releases"])


@router.get("/clientflow/releases")
def get_clientflow_releases(_user=Depends(get_current_superadmin_user)):
    try:
        return public_catalog()
    except ClientFlowCatalogError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
