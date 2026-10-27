"""Route policy and the route catalog (route_policy.py, route_catalog.py). Like Billing & rates, these are operator settings: the operator boundary
(operator_boundary.py) refuses them to agent processes."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

import projects
import route_catalog
import route_policy as rp
from deps import get_session
from settings import get_settings

router = APIRouter(prefix="/api/routes")


class PolicyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: rp.Policy
    confirm: bool


@router.get("")
def routes(feature: str = Query(..., max_length=20), project_id: int | None = Query(None, ge=1),
           s: Session = Depends(get_session)):
    """Allowed routes for one feature (and project), the default, and hidden routes with the reason each is hidden."""
    project = projects.get(s, project_id) if project_id else None
    try:
        return route_catalog.for_feature(s, get_settings(), feature, project)
    except rp.PolicyError as error:
        raise HTTPException(422, str(error)) from None


@router.get("/policy")
def get_policy(s: Session = Depends(get_session)):
    return route_catalog.policy_view(s, get_settings())


@router.put("/policy")
def put_policy(body: PolicyIn, s: Session = Depends(get_session)):
    """Save the app policy. A managed policy still applies on top of it; saving cannot widen what the installation allows."""
    if not body.confirm:
        raise HTTPException(422, "Explicit confirmation is required.")
    rp.save_app(s, body.policy)
    s.commit()
    return route_catalog.policy_view(s, get_settings())


class CostIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    free: bool | None = None
    membership: bool | None = None
    paid: bool | None = None


@router.patch("/policy/cost")
def patch_cost(body: CostIn, s: Session = Depends(get_session)):
    """Change only the app policy's cost classes (the switches shown in Model recovery). Paid API still needs approval per plan or task."""
    policy, _ = rp.load_app(s, get_settings())
    cost = policy.cost.model_copy(update={k: v for k, v in body.model_dump().items() if v is not None})
    rp.save_app(s, policy.model_copy(update={"cost": cost}))
    s.commit()
    return route_catalog.policy_view(s, get_settings())
