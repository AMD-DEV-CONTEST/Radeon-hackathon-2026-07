"""Prompt Profile API."""
from fastapi import APIRouter,HTTPException, Depends
from app.dependencies.auth import get_current_user_role, require_admin
from services.db import get_db
from services.audit_log import log_event
from fastapi import Depends
from services.database_registry import get_active_database_id, get_active_book_id
from services.prompt_engine.manager import PromptProfileManager
from services.prompt_engine.tester import PromptTester
router=APIRouter(tags=["prompt_profiles"]);_m=PromptProfileManager()
@router.get("/api/prompts/profiles")
def lp(role: str = Depends(get_current_user_role)):return{"profiles":_m.list()}
@router.post("/api/prompts/profiles")
def cp(d:dict, _: None = Depends(require_admin)):
 for r in["profile_id","name","content"]:
  if r not in d:raise HTTPException(400,f"Missing:{r}")
 result=_m.create(d["profile_id"],d["name"],d["content"])
 db=get_db()
 try:log_event(db,"prompt_profile.create",f"Prompt profile {d['profile_id']} created",target=d["profile_id"],database_id=get_active_database_id(),book_id=get_active_book_id(),success=True)
 finally:db.close()
 return{"status":"ok","profile":result}
@router.get("/api/prompts/profiles/{pid}")
def gp(pid:str, role: str = Depends(get_current_user_role)):
 p=_m.get(pid)
 if not p:raise HTTPException(404)
 return{"profile":p}
@router.put("/api/prompts/profiles/{pid}")
def up(pid:str,d:dict, _: None = Depends(require_admin)):
 result=_m.update(pid,d.get("content"),d.get("name"))
 db=get_db()
 try:log_event(db,"prompt_profile.update",f"Prompt profile {pid} updated",target=pid,database_id=get_active_database_id(),book_id=get_active_book_id(),success=True)
 finally:db.close()
 return{"status":"ok","result":result}
@router.post("/api/prompts/profiles/{pid}/activate")
def ap(pid:str, _: None = Depends(require_admin)):
 if not _m.get(pid):raise HTTPException(404)
 _m.activate(pid)
 db=get_db()
 try:log_event(db,"prompt_profile.activate",f"Prompt profile {pid} activated",target=pid,database_id=get_active_database_id(),book_id=get_active_book_id(),success=True)
 finally:db.close()
 return{"status":"ok","active":pid}
@router.post("/api/prompts/test")
def tp(d:dict, role: str = Depends(get_current_user_role)):return PromptTester().test(d.get("profile_id"),d.get("task_type","all"),d.get("variables"))
